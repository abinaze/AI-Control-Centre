"""Tests for the limits of the git state reader and what it never opens."""

import builtins
import os
import threading

from aic_control_centre.execution import git_state as git_module
from aic_control_centre.execution.git_state import (
    HEAD_BRANCH,
    HEAD_LIMIT,
    KIND_REPOSITORY,
    KIND_UNREADABLE,
    MAX_BRANCH_NAMES,
    PACKED_LIMIT,
    REF_LIMIT,
    REFLOG_TAIL,
    read_git_state,
)

C1 = "a1" * 20
C2 = "b2" * 20


def _git(tmp_path, head="ref: refs/heads/main\n", files=None):
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


def _padded(text, size):
    """Return the text with spaces after it, so that it has this size."""
    assert len(text) <= size

    return text + " " * (size - len(text))


def _packed_of_size(size):
    """Return the text of a packed-refs file of exactly this size."""
    base = f"{C1} refs/heads/main\n"

    return base + "#" + "x" * (size - len(base) - 2) + "\n"


def test_the_limits_have_the_values_that_are_documented() -> None:
    """A change of a limit is a change of what is read."""
    assert HEAD_LIMIT == 4096
    assert REF_LIMIT == 256
    assert PACKED_LIMIT == 8 * 1024 * 1024
    assert REFLOG_TAIL == 64 * 1024
    assert MAX_BRANCH_NAMES == 10_000


def test_head_is_read_at_its_limit_and_not_over_it(tmp_path) -> None:
    """4096 bytes are read, and 4097 are not."""
    text = "ref: refs/heads/main"
    at, _ = _git(
        tmp_path / "at",
        head=_padded(text, HEAD_LIMIT),
        files={"refs/heads/main": C1},
    )
    over, _ = _git(
        tmp_path / "over",
        head=_padded(text, HEAD_LIMIT + 1),
        files={"refs/heads/main": C1},
    )

    assert read_git_state(at).commit == C1

    state = read_git_state(over)

    assert state.kind == KIND_UNREADABLE
    assert state.detail == "HEAD is too large"


def test_a_ref_file_is_read_at_its_limit_and_not_over_it(tmp_path) -> None:
    """256 bytes are read, and 257 are not."""
    at, _ = _git(
        tmp_path / "at",
        files={"refs/heads/main": _padded(C1, REF_LIMIT)},
    )
    over, _ = _git(
        tmp_path / "over",
        files={"refs/heads/main": _padded(C1, REF_LIMIT + 1)},
    )

    assert read_git_state(at).commit == C1

    state = read_git_state(over)

    assert state.kind == KIND_REPOSITORY
    assert state.head == HEAD_BRANCH
    assert state.commit == ""
    assert state.commit_note == "the ref file is too large"


def test_packed_refs_is_read_at_its_limit_and_not_over_it(
    tmp_path,
    monkeypatch,
) -> None:
    """With a small limit, the edge is exact, and the notes say why."""
    monkeypatch.setattr(git_module, "PACKED_LIMIT", 200)
    at, _ = _git(tmp_path / "at", files={"packed-refs": _packed_of_size(200)})
    over, _ = _git(
        tmp_path / "over",
        files={"packed-refs": _packed_of_size(201)},
    )

    state = read_git_state(at)

    assert state.commit == C1
    assert state.branches == 1
    assert state.stash is False

    state = read_git_state(over)

    assert state.commit == ""
    assert state.unborn is False
    assert state.commit_note == "packed-refs is too large"
    assert state.branches is None
    assert state.branches_note == "packed-refs is too large"
    assert state.stash is None


def test_a_stash_file_is_known_although_packed_refs_is_too_large(
    tmp_path,
    monkeypatch,
) -> None:
    """A file that is there says yes, and nothing needs the pack."""
    monkeypatch.setattr(git_module, "PACKED_LIMIT", 200)
    project, _ = _git(
        tmp_path,
        files={
            "packed-refs": _packed_of_size(201),
            "refs/stash": C2 + "\n",
        },
    )

    assert read_git_state(project).stash is True


def test_a_long_reflog_gives_the_time_of_its_last_line(
    tmp_path,
    monkeypatch,
) -> None:
    """Only the end of the file is read, and a cut line is not used."""
    monkeypatch.setattr(git_module, "REFLOG_TAIL", 300)
    lines = [
        f"{C1} {C2} A Person <a@b.c> {1600000000 + number} +0000\tx\n"
        for number in range(50)
    ]
    lines.append(f"{C1} {C2} A Person <a@b.c> 1700000000 +0000\tlast\n")
    project, _ = _git(tmp_path, files={"logs/HEAD": "".join(lines)})

    assert read_git_state(project).last_change == "2023-11-14T22:13:20Z"


def test_a_tail_that_cuts_the_last_line_gives_nothing(
    tmp_path,
    monkeypatch,
) -> None:
    """A line that is cut is not believed."""
    monkeypatch.setattr(git_module, "REFLOG_TAIL", 20)
    log = f"{C1} {C2} A Person <a@b.c> 1700000000 +0000\tcommit: x\n"
    project, _ = _git(tmp_path, files={"logs/HEAD": log})

    assert read_git_state(project).last_change == ""


class _Spy:
    """A file that records the sizes that are read and where it seeks."""

    def __init__(self, handle, record):
        self._handle = handle
        self._record = record

    def __enter__(self):
        return self

    def __exit__(self, *details):
        self._handle.close()

    def read(self, size=-1):
        self._record["reads"].append(size)

        return self._handle.read(size)

    def seek(self, position, *rest):
        self._record["seeks"].append(position)

        return self._handle.seek(position, *rest)


def test_a_big_reflog_is_read_only_at_its_end(tmp_path, monkeypatch) -> None:
    """The size that is asked for is the tail, whatever the file holds."""
    line = f"{C1} {C2} A Person <a@b.c> 1700000000 +0000\tcommit: x\n"
    log = line * (3 * REFLOG_TAIL // len(line))
    project, git = _git(tmp_path, files={"logs/HEAD": log})
    target = os.path.join(os.fspath(git), "logs", "HEAD")
    record = {"reads": [], "seeks": []}
    real = builtins.open

    def spy(path, *arguments, **keywords):
        handle = real(path, *arguments, **keywords)

        if os.path.normpath(os.fspath(path)) == os.path.normpath(target):
            return _Spy(handle, record)

        return handle

    monkeypatch.setattr(builtins, "open", spy)

    state = read_git_state(project)

    assert state.last_change == "2023-11-14T22:13:20Z"
    assert record["reads"] == [REFLOG_TAIL]
    assert record["seeks"] == [len(log) - REFLOG_TAIL]


def test_the_branch_limit_is_exact(tmp_path, monkeypatch) -> None:
    """With the limit at 3, three are counted and four are not."""
    monkeypatch.setattr(git_module, "MAX_BRANCH_NAMES", 3)
    three, _ = _git(
        tmp_path / "three",
        files={f"refs/heads/b{n}": C1 for n in range(3)},
    )
    four, _ = _git(
        tmp_path / "four",
        files={f"refs/heads/b{n}": C1 for n in range(4)},
    )

    assert read_git_state(three).branches == 3

    state = read_git_state(four)

    assert state.branches is None
    assert state.branches_note == "more than 3 branches"
    assert state.kind == KIND_REPOSITORY


def test_packed_branches_count_toward_the_branch_limit(
    tmp_path,
    monkeypatch,
) -> None:
    """The names of both places are added up."""
    monkeypatch.setattr(git_module, "MAX_BRANCH_NAMES", 3)
    packed = "".join(f"{C1} refs/heads/p{n}\n" for n in range(2))
    three, _ = _git(
        tmp_path / "three",
        files={"refs/heads/main": C1, "packed-refs": packed},
    )
    four, _ = _git(
        tmp_path / "four",
        files={
            "refs/heads/main": C1,
            "refs/heads/other": C1,
            "packed-refs": packed,
        },
    )

    assert read_git_state(three).branches == 3

    state = read_git_state(four)

    assert state.branches is None
    assert state.branches_note == "more than 3 branches"


def test_only_four_files_are_ever_opened(tmp_path, monkeypatch) -> None:
    """The config, the index, the objects and the hooks stay closed."""
    project, git = _git(
        tmp_path,
        files={
            "config": "[remote]\n\turl = https://user:secret@example.com/x\n",
            "index": b"DIRC\x00\x00",
            "objects/ab/cdef": b"object",
            "hooks/post-checkout": "#!/bin/sh\ntouch ran\n",
            "description": "text",
            "info/exclude": "x",
            "refs/heads/main": C1 + "\n",
            "refs/heads/other": C2 + "\n",
            "refs/stash": C1 + "\n",
            "refs/remotes/origin/main": C1 + "\n",
            "packed-refs": f"{C2} refs/heads/old\n",
            "logs/HEAD": f"{C1} {C2} A <a@b.c> 1700000000 +0000\tx\n",
            "logs/refs/heads/main": "x",
            "MERGE_HEAD": C1 + "\n",
            "index.lock": "",
        },
    )
    root = os.path.normpath(os.fspath(git))
    opened = []
    real = builtins.open

    def record(path, *arguments, **keywords):
        if isinstance(path, (str, os.PathLike)):
            name = os.path.normpath(os.fspath(path))

            if name.startswith(root):
                opened.append(
                    os.path.relpath(name, root).replace("\\", "/")
                )

        return real(path, *arguments, **keywords)

    monkeypatch.setattr(builtins, "open", record)

    state = read_git_state(project)

    assert state.commit == C1
    assert sorted(opened) == [
        "HEAD",
        "logs/HEAD",
        "packed-refs",
        "refs/heads/main",
    ]


def test_a_ref_that_is_a_link_is_not_opened(tmp_path) -> None:
    """It checks nothing where a link cannot be made, as on Windows."""
    project, git = _git(tmp_path)
    secret = tmp_path / "secret"
    secret.write_bytes((C2 + "\n").encode())
    (git / "refs" / "heads").mkdir(parents=True)

    try:
        os.symlink(secret, git / "refs" / "heads" / "main")
    except (OSError, NotImplementedError):
        return

    state = read_git_state(project)

    assert state.commit == ""
    assert state.commit_note == "the ref file is not a regular file"
    assert state.branches == 0


def test_a_ref_that_is_a_pipe_does_not_block(tmp_path) -> None:
    """It checks nothing where a pipe cannot be made, as on Windows."""
    project, git = _git(tmp_path)
    (git / "refs" / "heads").mkdir(parents=True)

    try:
        os.mkfifo(git / "refs" / "heads" / "main")
    except (AttributeError, OSError):
        return

    results = []
    worker = threading.Thread(
        target=lambda: results.append(read_git_state(project)),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=20)

    assert not worker.is_alive()
    assert results[0].commit == ""
    assert results[0].commit_note == "the ref file is not a regular file"
    assert results[0].branches == 0
