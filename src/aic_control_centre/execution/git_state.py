"""Read the state of the git repository of a project, without changing it.

This is the work of the gitstate adapter. It reads a few small files in
the .git directory of a project and reports the branch, the commit, the
number of local branches, whether there is a stash, an operation in
progress or an index lock, and the time of the last change of HEAD. It
runs no program, so no git, no hook and no configuration is ever used.

Rules that matter:

- Only a fixed set of files is read: HEAD, the one ref that HEAD names,
  packed-refs, and the end of logs/HEAD. Everything else is only listed
  or looked at with lstat. The config file, the index, the objects and
  the hooks are never opened. The config file can hold a remote with a
  password in its address, so it is never read.
- A ref name comes from a file of the project, so it is data. It is
  used to build a path only when it starts with refs/ and has no empty
  part, no . or .. part, no backslash, no colon and no NUL. Otherwise
  nothing is opened.
- Before a file is opened it is looked at with lstat, and only a regular
  file that is not a link is read. A pipe or a link is not opened, so
  nothing can block and nothing outside the project is read.
- Every file has a size limit. A file over its limit is not read, and the
  report says so.
- A .git that is a link or a file (a worktree or a submodule) is not
  followed, and a repository that stores its refs as reftable is not
  read. The report says so and the outcome is still completed, so that
  a goal does not fail because of what this adapter does not read.
- Time is reported as a UTC time from the reflog, and never as an age,
  so the same repository gives the same report on any day.
- Names are escaped and cut before they are shown.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone

from aic_control_centre.execution.child_request import (
    RequestRefused,
    read_project_path,
    serve,
)
from aic_control_centre.execution.snapshot import escape_name, is_link
from aic_control_centre.projects.directory import directory_problem

HEAD_LIMIT = 4096
REF_LIMIT = 256
PACKED_LIMIT = 8 * 1024 * 1024
REFLOG_TAIL = 64 * 1024
MAX_BRANCH_NAMES = 10_000

KIND_REPOSITORY = "repository"
KIND_NONE = "none"
KIND_NOT_FOLLOWED = "not followed"
KIND_REFTABLE = "reftable"
KIND_UNREADABLE = "unreadable"

HEAD_BRANCH = "branch"
HEAD_DETACHED = "detached"
HEAD_OTHER = "other"
HEAD_UNREADABLE = "unreadable"

HEX = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
STAMP = re.compile(r">\s(\d{9,11})\s[+-]\d{4}")

OPERATION_FILES = (
    ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
    ("BISECT_LOG", "bisect"),
)
OPERATION_DIRECTORIES = ("rebase-merge", "rebase-apply")
REBASE = "rebase"

EARLIEST_STAMP = 10**9
LATEST_STAMP = 4 * 10**9

NAME_LIMIT = 60
NAME_OUTPUT_LIMIT = 120
COMMIT_SHOWN = 12

HEADS_PREFIX = "refs/heads/"
STASH_REF = "refs/stash"

PROBLEM_MISSING = "missing"
PROBLEM_NOT_REGULAR = "not a regular file"
PROBLEM_TOO_LARGE = "too large"


@dataclass(frozen=True)
class GitState:
    """What was read of the git repository of a project."""

    kind: str
    detail: str = ""
    head: str = ""
    ref: str = ""
    commit: str = ""
    unborn: bool = False
    commit_note: str = ""
    branches: int | None = None
    branches_note: str = ""
    stash: bool | None = None
    operations: tuple[str, ...] = ()
    lock: bool = False
    last_change: str = ""


def _exists(path: str) -> bool:
    """Return True if something is at the path. Links are not followed."""
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False

    return True


def _is_regular(path: str) -> bool:
    """Return True for a regular file that is not a link."""
    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False

    return stat.S_ISREG(info.st_mode) and not is_link(info)


def _read_limited(
    path: str, limit: int
) -> tuple[bytes | None, str | None]:
    """Read a small regular file, and say why if it was not read.

    The answer is the content and None, or None and a problem: missing,
    not a regular file, or too large. The file is looked at before it is
    opened, so a pipe or a link is never opened.
    """
    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None, PROBLEM_MISSING

    if is_link(info) or not stat.S_ISREG(info.st_mode):
        return None, PROBLEM_NOT_REGULAR

    if info.st_size > limit:
        return None, PROBLEM_TOO_LARGE

    with open(path, "rb") as handle:
        data = handle.read(limit + 1)

    if len(data) > limit:
        return None, PROBLEM_TOO_LARGE

    return data, None


def _ref_parts(name: str) -> tuple[str, ...] | None:
    """Return the parts of a ref name that is safe to use, or None."""
    if not name.startswith("refs/"):
        return None

    for bad in ("\\", "\x00", ":"):
        if bad in name:
            return None

    parts = tuple(name.split("/"))

    if any(part in ("", ".", "..") for part in parts):
        return None

    return parts


class _Packed:
    """The refs of packed-refs, read once and only when they are needed."""

    def __init__(self, git: str) -> None:
        self._path = os.path.join(git, "packed-refs")
        self._loaded = False
        self._refs: dict[str, str] | None = {}
        self._note = ""

    def get(self) -> tuple[dict[str, str] | None, str]:
        """Return the refs and a note, or None and why they were not read."""
        if not self._loaded:
            self._load()

        return self._refs, self._note

    def _load(self) -> None:
        self._loaded = True
        data, problem = _read_limited(self._path, PACKED_LIMIT)

        if problem == PROBLEM_MISSING:
            self._refs = {}

            return

        if data is None:
            self._refs = None
            self._note = f"packed-refs is {problem}"

            return

        refs: dict[str, str] = {}

        for line in data.decode("utf-8", "replace").split("\n"):
            line = line.rstrip("\r")

            if not line or line[0] in "#^" or " " not in line:
                continue

            commit, _, name = line.partition(" ")

            if HEX.fullmatch(commit):
                refs[name] = commit

        self._refs = refs


def _resolve_head(git: str, data: bytes, packed: _Packed) -> dict:
    """Return the fields that say what HEAD points at."""
    text = data.decode("utf-8", "replace").strip()

    if HEX.fullmatch(text):
        return {"head": HEAD_DETACHED, "commit": text}

    if not text.startswith("ref:"):
        return {
            "head": HEAD_UNREADABLE,
            "commit_note": "HEAD is not in a form that is read",
        }

    name = text[len("ref:"):].strip()
    parts = _ref_parts(name)

    if parts is None:
        return {
            "head": HEAD_UNREADABLE,
            "commit_note": "HEAD names a ref that is not read",
        }

    if name.startswith(HEADS_PREFIX):
        fields = {"head": HEAD_BRANCH, "ref": name[len(HEADS_PREFIX):]}
    else:
        fields = {"head": HEAD_OTHER, "ref": name}

    content, problem = _read_limited(os.path.join(git, *parts), REF_LIMIT)

    if problem == PROBLEM_MISSING:
        refs, note = packed.get()

        if refs is None:
            fields["commit_note"] = note
        elif name in refs:
            fields["commit"] = refs[name]
        else:
            fields["unborn"] = True

        return fields

    if content is None:
        fields["commit_note"] = f"the ref file is {problem}"

        return fields

    value = content.decode("utf-8", "replace").strip()

    if HEX.fullmatch(value):
        fields["commit"] = value
    else:
        fields["commit_note"] = "the ref file is not a commit id"

    return fields


def _loose_branches(git: str) -> set[str] | None:
    """Return the names under refs/heads, or None if there are too many."""
    names: set[str] = set()
    pending = [(os.path.join(git, "refs", "heads"), "")]

    while pending:
        directory, prefix = pending.pop()

        try:
            entries = list(os.scandir(directory))
        except (FileNotFoundError, NotADirectoryError):
            continue

        for entry in entries:
            info = os.lstat(entry.path)

            if is_link(info):
                continue

            name = prefix + entry.name

            if stat.S_ISDIR(info.st_mode):
                pending.append((entry.path, name + "/"))
            elif stat.S_ISREG(info.st_mode):
                names.add(name)

                if len(names) > MAX_BRANCH_NAMES:
                    return None

    return names


def _count_branches(git: str, packed: _Packed) -> tuple[int | None, str]:
    """Return the number of local branches, or None and why not."""
    too_many = f"more than {MAX_BRANCH_NAMES:,} branches"
    names = _loose_branches(git)

    if names is None:
        return None, too_many

    refs, note = packed.get()

    if refs is None:
        return None, note

    for name in refs:
        if name.startswith(HEADS_PREFIX):
            names.add(name[len(HEADS_PREFIX):])

    if len(names) > MAX_BRANCH_NAMES:
        return None, too_many

    return len(names), ""


def _stash(git: str, packed: _Packed) -> bool | None:
    """Return whether there is a stash, or None if that is not known."""
    if _is_regular(os.path.join(git, "refs", "stash")):
        return True

    refs, _note = packed.get()

    if refs is None:
        return None

    return STASH_REF in refs


def _operations(git: str) -> tuple[str, ...]:
    """Return the names of the operations that are in progress."""
    found = [
        name
        for marker, name in OPERATION_FILES
        if _exists(os.path.join(git, marker))
    ]

    if any(_exists(os.path.join(git, name)) for name in OPERATION_DIRECTORIES):
        found.append(REBASE)

    return tuple(found)


def _last_change(git: str) -> str:
    """Return the UTC time of the last line of the reflog of HEAD, or ''."""
    path = os.path.join(git, "logs", "HEAD")

    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return ""

    if is_link(info) or not stat.S_ISREG(info.st_mode):
        return ""

    start = max(0, info.st_size - REFLOG_TAIL)

    with open(path, "rb") as handle:
        handle.seek(start)
        data = handle.read(REFLOG_TAIL)

    lines = data.decode("utf-8", "replace").split("\n")

    if start > 0 and len(lines) > 1:
        lines = lines[1:]

    lines = [line for line in lines if line.strip()]

    if not lines:
        return ""

    found = STAMP.search(lines[-1])

    if found is None:
        return ""

    seconds = int(found.group(1))

    if not EARLIEST_STAMP <= seconds <= LATEST_STAMP:
        return ""

    moment = datetime.fromtimestamp(seconds, timezone.utc)

    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(root: str) -> GitState:
    git = os.path.join(root, ".git")

    try:
        info = os.lstat(git)
    except (FileNotFoundError, NotADirectoryError):
        return GitState(KIND_NONE)

    if is_link(info):
        return GitState(KIND_NOT_FOLLOWED, detail=".git is a link")

    if stat.S_ISREG(info.st_mode):
        return GitState(
            KIND_NOT_FOLLOWED,
            detail=".git is a file (a worktree or a submodule)",
        )

    if not stat.S_ISDIR(info.st_mode):
        return GitState(KIND_UNREADABLE, detail=".git is not a directory")

    try:
        reftable = os.lstat(os.path.join(git, "reftable"))
    except (FileNotFoundError, NotADirectoryError):
        reftable = None

    if reftable is not None and stat.S_ISDIR(reftable.st_mode):
        return GitState(KIND_REFTABLE)

    data, problem = _read_limited(os.path.join(git, "HEAD"), HEAD_LIMIT)

    if data is None:
        return GitState(KIND_UNREADABLE, detail=f"HEAD is {problem}")

    packed = _Packed(git)
    head = _resolve_head(git, data, packed)
    branches, branches_note = _count_branches(git, packed)

    return GitState(
        KIND_REPOSITORY,
        branches=branches,
        branches_note=branches_note,
        stash=_stash(git, packed),
        operations=_operations(git),
        lock=_exists(os.path.join(git, "index.lock")),
        last_change=_last_change(git),
        **head,
    )


def read_git_state(root) -> GitState:
    """Return what can be read of the git state of a project directory.

    A problem of the operating system is not raised. It is returned as a
    state of kind unreadable, with the reason that the system gave.
    """
    try:
        return _read(os.fspath(root))
    except OSError as error:
        return GitState(
            KIND_UNREADABLE, detail=error.strerror or type(error).__name__
        )


def _shown(name: str) -> str:
    """Return a name that is safe to print and short, however it escapes."""
    text = escape_name(name, limit=NAME_LIMIT)

    if len(text) > NAME_OUTPUT_LIMIT:
        return text[: NAME_OUTPUT_LIMIT - 3] + "..."

    return text


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def _head_part(state: GitState) -> str:
    short = state.commit[:COMMIT_SHOWN]
    name = _shown(state.ref)

    if state.head == HEAD_BRANCH:
        if state.commit:
            return f"branch {name} at {short}"

        if state.unborn:
            return f"no commit yet on branch {name}"

        return f"branch {name}; commit not read ({state.commit_note})"

    if state.head == HEAD_DETACHED:
        return f"detached HEAD at {short}"

    if state.head == HEAD_OTHER:
        if state.commit:
            return f"HEAD names {name} at {short}"

        if state.unborn:
            return f"HEAD names {name} with no commit yet"

        return f"HEAD names {name}; commit not read ({state.commit_note})"

    return f"HEAD not read ({state.commit_note})"


def _branches_part(state: GitState) -> str:
    if state.branches is None:
        return f"local branches not read ({state.branches_note})"

    if state.branches == 1:
        return "1 local branch"

    return f"{state.branches} local branches"


def _stash_part(state: GitState) -> str:
    if state.stash is None:
        return "stash: not read"

    return f"stash: {_yes(state.stash)}"


def describe(state: GitState) -> str:
    """Return the reason that reports a state, on one short line."""
    if state.kind == KIND_NONE:
        return "git state: not a git repository"

    if state.kind == KIND_NOT_FOLLOWED:
        return f"git state not read: {state.detail}, which is not followed"

    if state.kind == KIND_REFTABLE:
        return "git state not read: the refs are stored as reftable"

    if state.kind == KIND_UNREADABLE:
        return f"git state not read: {_shown(state.detail)}"

    operations = ", ".join(state.operations) or "none"
    changed = state.last_change or "unknown"
    parts = [
        _head_part(state),
        _branches_part(state),
        _stash_part(state),
        f"operation in progress: {operations}",
        f"index.lock: {_yes(state.lock)}",
        f"last HEAD change: {changed}",
    ]

    return "git state: " + "; ".join(parts)


# What follows is the child process. AIC starts it with a ProcessAdapter,
# writes the request to its standard input, and reads one JSON object from
# its standard output. See aic_control_centre.execution.process.


def run(request_bytes: bytes) -> dict[str, str]:
    """Return the outcome and reason for a request read from the parent.

    What could not be read is reported in the reason of a completed
    outcome. It is never a failed outcome, because a failed task fails its
    goal for good.
    """
    try:
        path = read_project_path(request_bytes, directory_problem)
    except RequestRefused as refused:
        return refused.outcome

    return {"outcome": "completed", "reason": describe(read_git_state(path))}


def main() -> int:
    """Read a request from standard input and print the answer as JSON."""
    return serve(run)


if __name__ == "__main__":
    raise SystemExit(main())
