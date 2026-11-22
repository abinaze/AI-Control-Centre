"""Tests for the report and the child process of the git state reader."""

import io
import json
import subprocess
import sys

from aic_control_centre.execution import git_state as git_module
from aic_control_centre.execution.child_request import PATH_LIMIT
from aic_control_centre.execution.git_state import (
    HEAD_BRANCH,
    HEAD_DETACHED,
    HEAD_OTHER,
    HEAD_UNREADABLE,
    KIND_NONE,
    KIND_NOT_FOLLOWED,
    KIND_REFTABLE,
    KIND_REPOSITORY,
    KIND_UNREADABLE,
    GitState,
    describe,
    main,
    read_git_state,
    run,
)
from aic_control_centre.execution.process import child_environment
from aic_control_centre.execution.snapshot import escape_name
from aic_control_centre.projects.directory import MISSING

MODULE = "aic_control_centre.execution.git_state"
C1 = "a1" * 20
C2 = "b2" * 20
SHORT = C1[:12]
TAIL = (
    "stash: no; operation in progress: none; index.lock: no; "
    "last HEAD change: unknown"
)


def _request(**fields):
    return json.dumps(fields).encode("utf-8")


def _shown(path):
    """The path as a reason shows it: backslashes are doubled on Windows."""
    return escape_name(str(path), limit=PATH_LIMIT)


def _state(**fields):
    """A state of a repository, with a branch and nothing else."""
    values = {
        "kind": KIND_REPOSITORY,
        "head": HEAD_BRANCH,
        "ref": "main",
        "commit": C1,
        "branches": 2,
        "stash": False,
    }
    values.update(fields)

    return GitState(**values)


def _repository(tmp_path, files=None):
    project = tmp_path / "project"
    git = project / ".git"
    git.mkdir(parents=True)
    (git / "HEAD").write_bytes(b"ref: refs/heads/main\n")

    for name, text in (files or {}).items():
        path = git / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    return project


def _tree(root):
    """Every path of a tree with the bytes of its files."""
    return sorted(
        (path.relative_to(root).as_posix(), path.read_bytes())
        if path.is_file()
        else (path.relative_to(root).as_posix(), None)
        for path in root.rglob("*")
    )


def test_a_directory_that_is_not_a_repository_is_described() -> None:
    """One short line."""
    assert describe(GitState(KIND_NONE)) == (
        "git state: not a git repository"
    )


def test_what_is_not_followed_is_described_as_such() -> None:
    """The detail is kept, and the line says that it is not followed."""
    link = GitState(KIND_NOT_FOLLOWED, detail=".git is a link")
    plain = GitState(
        KIND_NOT_FOLLOWED,
        detail=".git is a file (a worktree or a submodule)",
    )

    assert describe(link) == (
        "git state not read: .git is a link, which is not followed"
    )
    assert describe(plain) == (
        "git state not read: .git is a file (a worktree or a submodule), "
        "which is not followed"
    )


def test_reftable_and_unreadable_are_described() -> None:
    """The reason of the system is shown, escaped."""
    assert describe(GitState(KIND_REFTABLE)) == (
        "git state not read: the refs are stored as reftable"
    )
    assert describe(GitState(KIND_UNREADABLE, detail="HEAD is missing")) == (
        "git state not read: HEAD is missing"
    )
    assert describe(GitState(KIND_UNREADABLE, detail="a\x1b[2Jb")) == (
        "git state not read: a\\x1b[2Jb"
    )


def test_a_full_report_has_the_parts_in_order() -> None:
    """Every part, and the separators between them."""
    state = _state(
        branches=5,
        stash=True,
        operations=("merge", "rebase"),
        lock=True,
        last_change="2023-11-14T22:13:20Z",
    )

    assert describe(state) == (
        f"git state: branch main at {SHORT}; 5 local branches; stash: yes; "
        "operation in progress: merge, rebase; index.lock: yes; "
        "last HEAD change: 2023-11-14T22:13:20Z"
    )


def test_the_head_part_for_each_kind_of_head() -> None:
    """Branch, unborn, not read, detached, other and unreadable."""
    start = "git state: "
    middle = "; 2 local branches; " + TAIL

    assert describe(_state()) == f"{start}branch main at {SHORT}{middle}"
    assert describe(_state(commit="", unborn=True)) == (
        f"{start}no commit yet on branch main{middle}"
    )
    assert describe(_state(commit="", commit_note="the ref file is x")) == (
        f"{start}branch main; commit not read (the ref file is x){middle}"
    )
    assert describe(_state(head=HEAD_DETACHED, ref="")) == (
        f"{start}detached HEAD at {SHORT}{middle}"
    )
    assert describe(_state(head=HEAD_OTHER, ref="refs/remotes/o/m")) == (
        f"{start}HEAD names refs/remotes/o/m at {SHORT}{middle}"
    )
    assert describe(
        _state(head=HEAD_OTHER, ref="refs/x", commit="", unborn=True)
    ) == f"{start}HEAD names refs/x with no commit yet{middle}"
    assert describe(
        _state(head=HEAD_OTHER, ref="refs/x", commit="", commit_note="n")
    ) == f"{start}HEAD names refs/x; commit not read (n){middle}"
    assert describe(
        _state(head=HEAD_UNREADABLE, ref="", commit="", commit_note="why")
    ) == f"{start}HEAD not read (why){middle}"


def test_the_branch_count_is_worded_for_one_many_and_unknown() -> None:
    """One is singular, and a count that is not known says why."""
    assert "; 1 local branch; stash" in describe(_state(branches=1))
    assert "; 0 local branches; stash" in describe(_state(branches=0))
    assert "; 12 local branches; stash" in describe(_state(branches=12))
    assert (
        "; local branches not read (packed-refs is too large); stash"
        in describe(
            _state(branches=None, branches_note="packed-refs is too large")
        )
    )


def test_the_stash_lock_and_time_are_worded() -> None:
    """Yes, no and not read, and a time or unknown."""
    assert "stash: yes;" in describe(_state(stash=True))
    assert "stash: no;" in describe(_state(stash=False))
    assert "stash: not read;" in describe(_state(stash=None))
    assert "index.lock: yes;" in describe(_state(lock=True))
    assert "index.lock: no;" in describe(_state(lock=False))
    assert describe(_state(operations=("bisect",))).count(
        "operation in progress: bisect;"
    ) == 1
    assert describe(_state(last_change="2023-11-14T22:13:20Z")).endswith(
        "last HEAD change: 2023-11-14T22:13:20Z"
    )
    assert describe(_state()).endswith("last HEAD change: unknown")


def test_a_branch_name_is_escaped_and_cut() -> None:
    """Names come from the project, so they are data."""
    line = describe(_state(ref="a\x1b[2Jb\nc"))

    assert "branch a\\x1b[2Jb\\x0ac at" in line
    assert "\x1b" not in line
    assert "\n" not in line

    long_name = "x" * 500
    line = describe(_state(ref=long_name))

    assert f"branch {escape_name(long_name, limit=60)} at" in line
    assert len(line) < 300

    codes = "\x01" * 60
    line = describe(_state(ref=codes))
    shown = ("\\x01" * 60)[:117] + "..."

    assert len(shown) == 120
    assert f"branch {shown} at" in line


def test_no_secret_of_a_repository_is_in_the_report(tmp_path) -> None:
    """The config, the names and the messages are never read."""
    project = _repository(
        tmp_path,
        {
            "config": "[remote \"origin\"]\n\turl = https://u:hunter2@x.io/r\n"
            "[user]\n\tname = Secret Person\n\temail = secret@example.com\n",
            "refs/heads/main": C1 + "\n",
            "logs/HEAD": f"{C2} {C1} Secret Person <secret@example.com> "
            "1700000000 +0000\tcommit: the secret message\n",
        },
    )

    reason = run(_request(project_path=str(project)))["reason"]

    for word in ("hunter2", "Secret", "secret", "origin", "https", "@"):
        assert word not in reason, word


def test_run_reports_a_repository_as_completed(tmp_path) -> None:
    """The reason is the description, and the line is exact."""
    project = _repository(
        tmp_path,
        {
            "refs/heads/main": C1 + "\n",
            "logs/HEAD": f"{C2} {C1} A <a@b.c> 1700000000 +0000\tx\n",
        },
    )

    result = run(_request(project_path=str(project)))

    assert result == {
        "outcome": "completed",
        "reason": describe(read_git_state(project)),
    }
    assert result["reason"] == (
        f"git state: branch main at {SHORT}; 1 local branch; stash: no; "
        "operation in progress: none; index.lock: no; "
        "last HEAD change: 2023-11-14T22:13:20Z"
    )


def test_run_completes_for_what_it_could_not_read(tmp_path) -> None:
    """No repository, a reftable one and a broken one are not failures."""
    plain = tmp_path / "plain"
    plain.mkdir()
    reftable = _repository(tmp_path / "r")
    (reftable / ".git" / "reftable").mkdir()
    broken = _repository(tmp_path / "b")
    (broken / ".git" / "HEAD").unlink()

    assert run(_request(project_path=str(plain))) == {
        "outcome": "completed",
        "reason": "git state: not a git repository",
    }
    assert run(_request(project_path=str(reftable))) == {
        "outcome": "completed",
        "reason": "git state not read: the refs are stored as reftable",
    }
    assert run(_request(project_path=str(broken))) == {
        "outcome": "completed",
        "reason": "git state not read: HEAD is missing",
    }


def test_a_request_that_cannot_be_done_is_a_failed_answer(tmp_path) -> None:
    """The shared reader gives the texts, and nothing is read."""
    gone = tmp_path / "gone"
    afile = tmp_path / "afile"
    afile.write_bytes(b"x")

    assert run(b"\xff") == {
        "outcome": "failed",
        "reason": "the request was not valid UTF-8",
    }
    assert run(_request(task_id="t")) == {
        "outcome": "failed",
        "reason": "the request has no project path",
    }
    assert run(_request(project_path=str(gone))) == {
        "outcome": "failed",
        "reason": f"the project directory does not exist: {_shown(gone)}",
    }
    assert run(_request(project_path=str(afile))) == {
        "outcome": "failed",
        "reason": f"the project path is not a directory: {_shown(afile)}",
    }


def test_the_child_uses_its_own_check_of_the_directory(monkeypatch) -> None:
    """The check is looked up in this module, as it is in the others."""
    monkeypatch.setattr(
        git_module,
        "directory_problem",
        lambda path: (MISSING, ""),
    )

    assert run(_request(project_path="a\nb\x1b[2J")) == {
        "outcome": "failed",
        "reason": "the project directory does not exist: a\\x0ab\\x1b[2J",
    }


def test_main_prints_one_json_line(tmp_path, monkeypatch, capsys) -> None:
    """The line is the answer of run, and the status is zero."""
    project = _repository(tmp_path, {"refs/heads/main": C1 + "\n"})
    request = _request(project_path=str(project))

    class _Stdin:
        buffer = io.BytesIO(request)

    monkeypatch.setattr(sys, "stdin", _Stdin())

    assert main() == 0

    output = capsys.readouterr().out

    assert output == json.dumps(run(request)) + "\n"
    assert json.loads(output)["outcome"] == "completed"


def _child(tmp_path, payload):
    """Run the module as the adapter does: a child, with a clean setting."""
    workdir = tmp_path / "empty"
    workdir.mkdir(exist_ok=True)

    return subprocess.run(
        [sys.executable, "-B", "-m", MODULE],
        input=payload,
        capture_output=True,
        cwd=workdir,
        env=child_environment(),
        timeout=60,
    )


def test_the_module_runs_as_a_child_process(tmp_path) -> None:
    """It works with the environment and directory a child is given."""
    project = _repository(
        tmp_path,
        {
            "refs/heads/main": C1 + "\n",
            "hooks/post-checkout": "#!/bin/sh\ntouch ran\n",
        },
    )
    before = _tree(project)

    done = _child(tmp_path, _request(project_path=str(project)))

    assert done.returncode == 0
    assert done.stderr == b""

    lines = done.stdout.decode("utf-8").splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0]) == run(_request(project_path=str(project)))
    assert _tree(project) == before


def test_a_child_answers_a_bad_request_with_status_zero(tmp_path) -> None:
    """The parent reads an answer, and no traceback is printed."""
    done = _child(tmp_path, b"not json")

    assert done.returncode == 0
    assert done.stderr == b""
    assert json.loads(done.stdout) == {
        "outcome": "failed",
        "reason": "the request was not valid JSON",
    }


def test_a_child_answers_a_payload_that_is_not_an_object(tmp_path) -> None:
    """A list, a number and an empty path are all answers."""
    for payload in (b"[]", b"3", b'{"project_path": ""}', b""):
        done = _child(tmp_path, payload)

        assert done.returncode == 0, payload
        assert done.stderr == b"", payload
        assert json.loads(done.stdout)["outcome"] == "failed", payload
