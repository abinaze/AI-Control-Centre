"""Tests of the git state reader against repositories that git made.

Each test returns early where git is not installed, and then it checks
nothing. Git runs with no user or system configuration and with a fixed
identity and date, so the repository does not depend on the machine.
"""

import os
import shutil
import subprocess

from aic_control_centre.execution.git_state import (
    HEAD_BRANCH,
    HEAD_DETACHED,
    KIND_REPOSITORY,
    read_git_state,
)

STAMP = "1700000000 +0000"
TIME = "2023-11-14T22:13:20Z"


def _environment(home):
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(home),
            "GIT_AUTHOR_NAME": "A Person",
            "GIT_AUTHOR_EMAIL": "a@example.com",
            "GIT_COMMITTER_NAME": "A Person",
            "GIT_COMMITTER_EMAIL": "a@example.com",
            "GIT_AUTHOR_DATE": STAMP,
            "GIT_COMMITTER_DATE": STAMP,
        }
    )

    return environment


def _git(project, *arguments, check=True):
    """Run git in the project and return its output without the newline."""
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *arguments],
        cwd=project,
        env=_environment(project.parent),
        capture_output=True,
        text=True,
        timeout=60,
    )

    if check:
        assert done.returncode == 0, done.stderr

    return done.stdout.strip()


def _repository(tmp_path, commit=True):
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")

    if commit:
        (project / "a.txt").write_bytes(b"one\n")
        _git(project, "add", "a.txt")
        _git(project, "commit", "-q", "-m", "first")

    return project


def test_a_repository_that_git_made_agrees_with_git(tmp_path) -> None:
    """The commit, the branch, the count and the time."""
    if shutil.which("git") is None:
        return

    project = _repository(tmp_path)

    state = read_git_state(project)

    assert state.kind == KIND_REPOSITORY
    assert state.head == HEAD_BRANCH
    assert state.ref == _git(project, "branch", "--show-current")
    assert state.commit == _git(project, "rev-parse", "HEAD")
    assert state.branches == 1
    assert state.stash is False
    assert state.operations == ()
    assert state.lock is False
    assert state.last_change == TIME


def test_refs_that_git_packed_are_read(tmp_path) -> None:
    """After pack-refs the loose files are gone, and the answer is not."""
    if shutil.which("git") is None:
        return

    project = _repository(tmp_path)
    _git(project, "branch", "other")
    _git(project, "branch", "third")
    _git(project, "pack-refs", "--all")

    assert not (project / ".git" / "refs" / "heads" / "main").exists()

    state = read_git_state(project)

    assert state.commit == _git(project, "rev-parse", "HEAD")
    assert state.branches == 3
    assert state.unborn is False


def test_a_detached_head_that_git_made_is_read(tmp_path) -> None:
    """The commit is in HEAD."""
    if shutil.which("git") is None:
        return

    project = _repository(tmp_path)
    _git(project, "checkout", "-q", "--detach")

    state = read_git_state(project)

    assert state.head == HEAD_DETACHED
    assert state.commit == _git(project, "rev-parse", "HEAD")


def test_a_stash_that_git_made_is_found(tmp_path) -> None:
    """The stash is a ref, and it is seen."""
    if shutil.which("git") is None:
        return

    project = _repository(tmp_path)
    (project / "a.txt").write_bytes(b"two\n")
    _git(project, "stash", "push", "-q")

    assert read_git_state(project).stash is True


def test_a_merge_that_stopped_is_seen(tmp_path) -> None:
    """A conflict leaves MERGE_HEAD, and that is an operation."""
    if shutil.which("git") is None:
        return

    project = _repository(tmp_path)
    _git(project, "checkout", "-q", "-b", "other")
    (project / "a.txt").write_bytes(b"other\n")
    _git(project, "commit", "-q", "-am", "other")
    _git(project, "checkout", "-q", "main")
    (project / "a.txt").write_bytes(b"main\n")
    _git(project, "commit", "-q", "-am", "main")
    _git(project, "merge", "other", check=False)

    assert (project / ".git" / "MERGE_HEAD").exists()
    assert read_git_state(project).operations == ("merge",)


def test_a_repository_with_no_commit_is_unborn(tmp_path) -> None:
    """HEAD names a branch that does not exist yet."""
    if shutil.which("git") is None:
        return

    project = _repository(tmp_path, commit=False)

    state = read_git_state(project)

    assert state.head == HEAD_BRANCH
    assert state.ref == "main"
    assert state.unborn is True
    assert state.commit == ""
    assert state.branches == 0
