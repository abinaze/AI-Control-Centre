"""Tests for reading the state of a git repository."""

import os
import stat

import pytest

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
    read_git_state,
)

C1 = "a1" * 20
C2 = "b2" * 20
C3 = "c3" * 20
LONG = "d4" * 32


def _git(tmp_path, head="ref: refs/heads/main\n", files=None):
    """Make a project with a .git directory, and return both."""
    project = tmp_path / "project"
    git = project / ".git"
    git.mkdir(parents=True)

    if head is not None:
        (git / "HEAD").write_bytes(head.encode("utf-8"))

    for name, text in (files or {}).items():
        path = git / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode())

    return project, git


def _log(stamp, commit=C1):
    return f"{C2} {commit} A Person <a@b.c> {stamp} +0000\tcommit: x\n"


def test_a_branch_with_a_loose_ref_is_read(tmp_path) -> None:
    """The branch, the commit and everything that is not there."""
    project, _ = _git(tmp_path, files={"refs/heads/main": C1 + "\n"})

    state = read_git_state(project)

    assert state.kind == KIND_REPOSITORY
    assert state.head == HEAD_BRANCH
    assert state.ref == "main"
    assert state.commit == C1
    assert state.unborn is False
    assert state.commit_note == ""
    assert state.branches == 1
    assert state.branches_note == ""
    assert state.stash is False
    assert state.operations == ()
    assert state.lock is False
    assert state.last_change == ""


def test_a_branch_with_a_packed_ref_is_read(tmp_path) -> None:
    """A ref that is only in packed-refs gives the commit."""
    packed = f"# pack-refs with: peeled\n{C1} refs/heads/main\n"
    project, _ = _git(tmp_path, files={"packed-refs": packed})

    state = read_git_state(project)

    assert state.head == HEAD_BRANCH
    assert state.commit == C1
    assert state.unborn is False
    assert state.branches == 1


def test_a_loose_ref_wins_over_a_packed_one(tmp_path) -> None:
    """The loose file is the newer of the two."""
    project, _ = _git(
        tmp_path,
        files={
            "refs/heads/main": C1 + "\n",
            "packed-refs": f"{C2} refs/heads/main\n",
        },
    )

    assert read_git_state(project).commit == C1


def test_a_name_in_both_places_is_counted_once(tmp_path) -> None:
    """Loose main and other, packed main and feature, make three."""
    project, _ = _git(
        tmp_path,
        files={
            "refs/heads/main": C1 + "\n",
            "refs/heads/other": C2 + "\n",
            "packed-refs": f"{C3} refs/heads/main\n{C3} refs/heads/feature\n"
            f"{C3} refs/tags/v1\n{C3} refs/remotes/origin/main\n",
        },
    )

    assert read_git_state(project).branches == 3


def test_a_branch_name_with_a_slash_is_one_branch(tmp_path) -> None:
    """The folders under refs/heads are not branches themselves."""
    project, _ = _git(
        tmp_path,
        head="ref: refs/heads/feature/x\n",
        files={
            "refs/heads/feature/x": C1 + "\n",
            "refs/heads/feature/deep/y": C2 + "\n",
            "refs/heads/main": C3 + "\n",
        },
    )

    state = read_git_state(project)

    assert state.ref == "feature/x"
    assert state.commit == C1
    assert state.branches == 3


def test_a_detached_head_is_read(tmp_path) -> None:
    """The commit is in HEAD itself."""
    project, _ = _git(tmp_path, head=C1 + "\n")

    state = read_git_state(project)

    assert state.kind == KIND_REPOSITORY
    assert state.head == HEAD_DETACHED
    assert state.commit == C1
    assert state.ref == ""
    assert state.branches == 0


def test_a_detached_head_with_a_long_id_is_read(tmp_path) -> None:
    """A repository with sha256 has ids of 64 characters."""
    project, _ = _git(tmp_path, head=LONG + "\n")

    state = read_git_state(project)

    assert state.head == HEAD_DETACHED
    assert state.commit == LONG


def test_a_branch_with_no_commit_is_unborn(tmp_path) -> None:
    """Nothing in the ref files and nothing packed."""
    project, _ = _git(tmp_path)

    state = read_git_state(project)

    assert state.head == HEAD_BRANCH
    assert state.ref == "main"
    assert state.unborn is True
    assert state.commit == ""
    assert state.commit_note == ""
    assert state.branches == 0


def test_a_branch_missing_from_packed_refs_is_unborn(tmp_path) -> None:
    """The pack is read, and the name is not in it."""
    project, _ = _git(
        tmp_path,
        files={"packed-refs": f"{C1} refs/heads/other\n^{C2}\n"},
    )

    state = read_git_state(project)

    assert state.unborn is True
    assert state.commit == ""
    assert state.branches == 1


def test_a_ref_that_is_not_a_branch_is_other(tmp_path) -> None:
    """The whole name is kept, and the commit is read."""
    project, _ = _git(
        tmp_path,
        head="ref: refs/remotes/origin/main\n",
        files={"refs/remotes/origin/main": C2 + "\n"},
    )

    state = read_git_state(project)

    assert state.head == HEAD_OTHER
    assert state.ref == "refs/remotes/origin/main"
    assert state.commit == C2
    assert state.branches == 0


def test_a_head_that_is_not_understood_is_not_read(tmp_path) -> None:
    """Text that is neither a commit nor a ref."""
    project, _ = _git(tmp_path, head="hello there\n")

    state = read_git_state(project)

    assert state.kind == KIND_REPOSITORY
    assert state.head == HEAD_UNREADABLE
    assert state.commit == ""
    assert state.commit_note == "HEAD is not in a form that is read"


def test_a_ref_file_that_is_not_a_commit_id_is_noted(tmp_path) -> None:
    """The text of the file is not used."""
    project, _ = _git(
        tmp_path,
        files={"refs/heads/main": "ref: refs/heads/other\n"},
    )

    state = read_git_state(project)

    assert state.head == HEAD_BRANCH
    assert state.commit == ""
    assert state.unborn is False
    assert state.commit_note == "the ref file is not a commit id"


UNSAFE = [
    "ref: ../secret",
    "ref: refs/../../secret",
    "ref: refs/heads/../../secret",
    "ref: /etc/passwd",
    "ref: refs//x",
    "ref: refs/./x",
    "ref: refs/heads/",
    "ref: refs\\x",
    "ref: refs/a:b",
    "ref: other/x",
    "ref: refs/a\x00b",
    "ref: refs/a\\..\\..\\secret",
]


def test_a_ref_name_that_leaves_the_refs_is_never_opened(tmp_path) -> None:
    """Each name is refused before any path is made from it."""
    project, git = _git(tmp_path)
    (git / "secret").write_bytes((C3 + "\n").encode())
    (project / "secret").write_bytes((C3 + "\n").encode())

    for head in UNSAFE:
        (git / "HEAD").write_bytes((head + "\n").encode("utf-8"))

        state = read_git_state(project)

        assert state.kind == KIND_REPOSITORY, head
        assert state.head == HEAD_UNREADABLE, head
        assert state.commit == "", head
        assert state.commit_note == "HEAD names a ref that is not read", head


def test_a_loose_stash_is_found(tmp_path) -> None:
    """The file refs/stash is a stash."""
    project, _ = _git(tmp_path, files={"refs/stash": C1 + "\n"})

    assert read_git_state(project).stash is True


def test_a_packed_stash_is_found(tmp_path) -> None:
    """A stash can be in packed-refs after a pack."""
    project, _ = _git(
        tmp_path,
        files={"packed-refs": f"{C1} refs/stash\n"},
    )

    assert read_git_state(project).stash is True


def test_no_stash_is_no_stash(tmp_path) -> None:
    """Neither a file nor a packed name."""
    project, _ = _git(
        tmp_path,
        files={"packed-refs": f"{C1} refs/heads/main\n"},
    )

    assert read_git_state(project).stash is False


def test_each_operation_in_progress_is_named(tmp_path) -> None:
    """One marker at a time, with the name that is shown for it."""
    markers = {
        "MERGE_HEAD": ("file", "merge"),
        "CHERRY_PICK_HEAD": ("file", "cherry-pick"),
        "REVERT_HEAD": ("file", "revert"),
        "BISECT_LOG": ("file", "bisect"),
        "rebase-merge": ("dir", "rebase"),
        "rebase-apply": ("dir", "rebase"),
    }

    for number, (name, (kind, shown)) in enumerate(markers.items()):
        project, git = _git(tmp_path / f"p{number}")

        if kind == "file":
            (git / name).write_bytes(C1.encode())
        else:
            (git / name).mkdir()

        assert read_git_state(project).operations == (shown,), name


def test_two_rebase_directories_are_one_rebase(tmp_path) -> None:
    """The order is that of the markers, and a rebase comes last."""
    project, git = _git(tmp_path)
    (git / "rebase-merge").mkdir()
    (git / "rebase-apply").mkdir()
    (git / "BISECT_LOG").write_bytes(b"")
    (git / "MERGE_HEAD").write_bytes(C1.encode())

    assert read_git_state(project).operations == ("merge", "bisect", "rebase")


def test_an_index_lock_is_noticed(tmp_path) -> None:
    """The file is looked at and never opened."""
    project, _ = _git(tmp_path, files={"index.lock": ""})

    assert read_git_state(project).lock is True


def test_the_last_line_of_the_reflog_gives_the_time(tmp_path) -> None:
    """A UTC time, from the last line."""
    log = _log(1600000000) + _log(1700000000) + "\n"
    project, _ = _git(tmp_path, files={"logs/HEAD": log})

    assert read_git_state(project).last_change == "2023-11-14T22:13:20Z"


def test_a_reflog_of_one_line_gives_the_time(tmp_path) -> None:
    """With a newline at the end or without, the one line is the last."""
    for number, text in enumerate(
        [_log(1700000000), _log(1700000000).rstrip("\n")]
    ):
        project, _ = _git(tmp_path / f"p{number}", files={"logs/HEAD": text})

        assert read_git_state(project).last_change == "2023-11-14T22:13:20Z"


def test_an_empty_reflog_or_one_in_another_format_gives_nothing(
    tmp_path,
) -> None:
    """Unknown is better than a guess."""
    for number, text in enumerate(["", "\n\n", "no time here\n"]):
        project, _ = _git(tmp_path / f"p{number}", files={"logs/HEAD": text})

        assert read_git_state(project).last_change == "", text


def test_a_time_out_of_range_gives_nothing(tmp_path) -> None:
    """Before 2001-09-09 and after 2096-10-02 are not believed."""
    for number, stamp in enumerate([999999999, 4000000001, 99999999999]):
        project, _ = _git(
            tmp_path / f"p{number}",
            files={"logs/HEAD": _log(stamp)},
        )

        assert read_git_state(project).last_change == "", stamp


def test_the_edges_of_the_time_range_are_believed(tmp_path) -> None:
    """Both ends are inside."""
    first, _ = _git(
        tmp_path / "first",
        files={"logs/HEAD": _log(1000000000)},
    )
    last, _ = _git(
        tmp_path / "last",
        files={"logs/HEAD": _log(4000000000)},
    )

    assert read_git_state(first).last_change == "2001-09-09T01:46:40Z"
    assert read_git_state(last).last_change == "2096-10-02T07:06:40Z"


def test_a_directory_without_git_is_not_a_repository(tmp_path) -> None:
    """Nothing is there."""
    project = tmp_path / "project"
    project.mkdir()

    state = read_git_state(project)

    assert state.kind == KIND_NONE
    assert state.detail == ""


def test_a_git_file_is_not_followed(tmp_path) -> None:
    """A worktree or a submodule points elsewhere, and that is not read."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").write_bytes(b"gitdir: ../elsewhere\n")

    state = read_git_state(project)

    assert state.kind == KIND_NOT_FOLLOWED
    assert state.detail == ".git is a file (a worktree or a submodule)"
    assert state.head == ""


def test_a_git_link_is_not_followed(tmp_path) -> None:
    """It checks nothing where a link cannot be made, as on Windows."""
    real, _ = _git(tmp_path / "real", files={"refs/heads/main": C1 + "\n"})
    project = tmp_path / "project"
    project.mkdir()

    try:
        os.symlink(real / ".git", project / ".git", target_is_directory=True)
    except (OSError, NotImplementedError):
        return

    state = read_git_state(project)

    assert state.kind == KIND_NOT_FOLLOWED
    assert state.detail == ".git is a link"
    assert state.commit == ""


def test_a_git_pipe_is_not_a_directory(tmp_path) -> None:
    """It checks nothing where a pipe cannot be made, as on Windows."""
    project = tmp_path / "project"
    project.mkdir()

    try:
        os.mkfifo(project / ".git")
    except (AttributeError, OSError):
        return

    state = read_git_state(project)

    assert state.kind == KIND_UNREADABLE
    assert state.detail == ".git is not a directory"


def test_reftable_is_noticed_and_not_read(tmp_path) -> None:
    """The directory is enough, and HEAD is not looked at."""
    project, git = _git(tmp_path, head="ref: refs/heads/.invalid\n")
    (git / "reftable").mkdir()

    state = read_git_state(project)

    assert state.kind == KIND_REFTABLE
    assert state.head == ""


def test_a_missing_head_is_unreadable(tmp_path) -> None:
    """A .git with no HEAD is not a repository that is read."""
    project, _ = _git(tmp_path, head=None)

    state = read_git_state(project)

    assert state.kind == KIND_UNREADABLE
    assert state.detail == "HEAD is missing"


def test_a_head_that_is_not_a_regular_file_is_not_opened(tmp_path) -> None:
    """A directory named HEAD is not read."""
    project, git = _git(tmp_path, head=None)
    (git / "HEAD").mkdir()

    state = read_git_state(project)

    assert state.kind == KIND_UNREADABLE
    assert state.detail == "HEAD is not a regular file"


def test_an_error_of_the_system_is_a_state_and_not_a_traceback(
    tmp_path,
    monkeypatch,
) -> None:
    """The reason of the system is the detail."""
    project, _ = _git(tmp_path)
    real = os.lstat

    def refuse(path, *arguments, **keywords):
        if os.path.basename(os.fspath(path)) == "HEAD":
            raise PermissionError(13, "Access is denied")

        return real(path, *arguments, **keywords)

    monkeypatch.setattr(os, "lstat", refuse)

    state = read_git_state(project)

    assert state.kind == KIND_UNREADABLE
    assert state.detail == "Access is denied"


def test_an_error_without_a_reason_gives_its_class_name(
    tmp_path,
    monkeypatch,
) -> None:
    """The text can be empty, so the name of the class stands in."""
    project, _ = _git(tmp_path)
    real = os.lstat

    def refuse(path, *arguments, **keywords):
        if os.path.basename(os.fspath(path)) == "HEAD":
            raise PermissionError()

        return real(path, *arguments, **keywords)

    monkeypatch.setattr(os, "lstat", refuse)

    assert read_git_state(project).detail == "PermissionError"


def test_the_same_repository_gives_the_same_state(tmp_path) -> None:
    """Nothing depends on the day or on an earlier call."""
    project, _ = _git(
        tmp_path,
        files={
            "refs/heads/main": C1 + "\n",
            "logs/HEAD": _log(1700000000),
            "refs/stash": C2 + "\n",
        },
    )

    first = read_git_state(project)
    second = read_git_state(str(project))

    assert first == second
    assert hash(first) == hash(second)


def test_a_state_cannot_be_changed(tmp_path) -> None:
    """The state is a frozen record."""
    project, _ = _git(tmp_path)
    state = read_git_state(project)

    with pytest.raises(AttributeError):
        state.kind = KIND_NONE  # type: ignore[misc]

    assert stat.S_ISDIR(os.lstat(project / ".git").st_mode)
