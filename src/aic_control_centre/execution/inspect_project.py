"""Look at a project directory and describe it, without changing it.

This is the work of the inspect adapter. It walks a directory and counts
what is in it: files, directories, links, and anything else. It adds up the
size of the files, keeps the largest three, and notes whether a README and
a .git exist at the top.

Rules that matter:

- Nothing is opened. Only the directory listing and the status of each
  entry are read, so no file content is read and no pipe can block.
- A link is counted and never followed, so a link that points outside the
  project, or back into it, adds nothing.
- Something that cannot be read is counted as unreadable and the walk goes
  on. The count is not exclusive: a directory that cannot be listed is
  also counted as a directory.
- Names come from the project, so they are data. They are escaped and cut
  before they are shown.
- The top level is the only place where a README or .git is looked for.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

from aic_control_centre.execution.snapshot import escape_name, is_link
from aic_control_centre.projects.directory import (
    MISSING,
    NOT_A_DIRECTORY,
    directory_problem,
)

LARGEST_SHOWN = 3
NAME_LIMIT = 60
NAME_OUTPUT_LIMIT = 120
SIZE_UNITS = ("KiB", "MiB", "GiB", "TiB")


@dataclass
class Summary:
    """What a walk of a project directory found."""

    files: int = 0
    directories: int = 0
    links: int = 0
    other: int = 0
    unreadable: int = 0
    total_bytes: int = 0
    largest: list[tuple[int, str]] = field(default_factory=list)
    has_readme: bool = False
    has_git: bool = False


def record(summary: Summary, name: str, info) -> bool:
    """Add one entry to a summary and say whether to look inside it.

    The name is relative to the project, with "/" between the parts, and
    the status is that of the entry itself, with links not followed. Only
    a directory is looked inside.
    """
    top = "/" not in name
    lowered = name.lower()

    if is_link(info):
        summary.links += 1
        _note_top(summary, top, lowered, readme=True)

        return False

    if stat.S_ISDIR(info.st_mode):
        summary.directories += 1
        _note_top(summary, top, lowered, readme=False)

        return True

    if stat.S_ISREG(info.st_mode):
        summary.files += 1
        summary.total_bytes += info.st_size
        summary.largest.append((info.st_size, name))
        summary.largest.sort(key=lambda item: (-item[0], item[1]))
        del summary.largest[LARGEST_SHOWN:]
        _note_top(summary, top, lowered, readme=True)

        return False

    summary.other += 1
    _note_top(summary, top, lowered, readme=False)

    return False


def _note_top(summary: Summary, top: bool, lowered: str, readme: bool) -> None:
    """Note a README or a .git, if this is a top level entry."""
    if not top:
        return

    if readme and lowered.startswith("readme"):
        summary.has_readme = True

    if lowered == ".git":
        summary.has_git = True


def inspect_directory(root: Path | str) -> Summary:
    """Walk a directory and return what is in it.

    The directory itself must be readable, and an OSError says why it is
    not. Anything below it that cannot be read is counted as unreadable.
    """
    summary = Summary()
    pending = [("", os.fspath(root))]

    while pending:
        prefix, directory = pending.pop()

        try:
            with os.scandir(directory) as scan:
                children = list(scan)
        except OSError:
            if not prefix:
                raise

            summary.unreadable += 1
            continue

        for child in children:
            name = prefix + child.name

            try:
                info = child.stat(follow_symlinks=False)
            except OSError:
                summary.unreadable += 1
                continue

            if record(summary, name, info):
                pending.append((name + "/", child.path))

    return summary


def format_size(size: int) -> str:
    """Return a size in bytes, or with one decimal in a larger unit."""
    if size < 1024:
        return f"{size} B"

    value = size / 1024

    for unit in SIZE_UNITS:
        if round(value, 1) < 1024 or unit == SIZE_UNITS[-1]:
            return f"{value:.1f} {unit}"

        value /= 1024

    return f"{value:.1f} {SIZE_UNITS[-1]}"


def _shown(name: str) -> str:
    """Return a name that is safe to print and short, however it escapes."""
    text = escape_name(name, limit=NAME_LIMIT)

    if len(text) > NAME_OUTPUT_LIMIT:
        return text[: NAME_OUTPUT_LIMIT - 3] + "..."

    return text


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def describe(summary: Summary) -> str:
    """Return the reason that reports a summary, on one short line."""
    parts = [
        f"{summary.files} files",
        f"{summary.directories} directories",
        format_size(summary.total_bytes),
    ]

    if summary.links:
        parts.append(f"{summary.links} links not followed")

    if summary.other:
        parts.append(f"{summary.other} other")

    if summary.unreadable:
        parts.append(f"{summary.unreadable} unreadable")

    if summary.largest:
        largest = ", ".join(
            f"{_shown(name)} ({format_size(size)})"
            for size, name in summary.largest
        )
    else:
        largest = "none"

    return (
        f"inspected project: {', '.join(parts)}; largest: {largest}; "
        f"README: {_yes(summary.has_readme)}; .git: {_yes(summary.has_git)}"
    )


# What follows is the child process. AIC starts it with a ProcessAdapter,
# writes the request to its standard input, and reads one JSON object from
# its standard output. See aic_control_centre.execution.process.

PATH_LIMIT = 120


def _failed(reason: str) -> dict[str, str]:
    return {"outcome": "failed", "reason": reason}


def _shown_path(path: str) -> str:
    return escape_name(path, limit=PATH_LIMIT)


def run(request_bytes: bytes) -> dict[str, str]:
    """Return the outcome and reason for a request read from the parent."""
    try:
        text = request_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return _failed("the request was not valid UTF-8")

    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return _failed("the request was not valid JSON")

    path = data.get("project_path") if isinstance(data, dict) else None

    if not isinstance(path, str) or not path:
        return _failed("the request has no project path")

    shown = _shown_path(path)
    problem = directory_problem(Path(path))

    if problem is not None:
        kind, detail = problem

        if kind == MISSING:
            return _failed(f"the project directory does not exist: {shown}")

        if kind == NOT_A_DIRECTORY:
            return _failed(f"the project path is not a directory: {shown}")

        return _failed(
            f"the project directory cannot be read: {shown}; {detail}"
        )

    try:
        summary = inspect_directory(path)
    except OSError as error:
        reason = error.strerror or type(error).__name__

        return _failed(
            f"the project directory cannot be read: "
            f"{escape_name(reason, limit=PATH_LIMIT)}"
        )

    return {"outcome": "completed", "reason": describe(summary)}


def main() -> int:
    """Read a request from standard input and print the answer as JSON."""
    print(json.dumps(run(sys.stdin.buffer.read())))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
