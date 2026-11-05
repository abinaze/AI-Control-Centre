"""Check the syntax of the Python files in a project directory.

This is the library of the Python syntax check adapter. It reads the files
of a project, which makes it the first AIC code that reads the content of
a person's files on purpose, so it is strict about how it does it:

- Nothing is imported, run or written. A file is compiled to a code
  object that is thrown away, and the compile step writes no bytecode.
- Only regular files whose name ends in .py are read. A link is never
  followed. A file is opened without blocking and without following a
  link, and the open descriptor is checked to be a regular file, so a
  pipe, or a file that was swapped for a pipe, is skipped and cannot hang
  the run.
- The problems are listed in the order of their names, so the same
  project gives the same report however the system lists its files.
- Names and error texts come from the project, so they are escaped and
  cut before they go into a reason.
- The limits are numbers and never a clock, so a project always gets the
  same answer.

The grammar is that of the Python that runs AIC, and the reason says
which one that is.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

from aic_control_centre.execution.inspect_project import (
    NAME_LIMIT,
    format_size,
)
from aic_control_centre.execution.snapshot import escape_name, is_link

MAX_FILE_BYTES = 1024 * 1024
MAX_FILES = 10000
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MESSAGE_LIMIT = 60
ERRORS_SHOWN = 3
CHUNK_BYTES = 65536
PYTHON_SUFFIX = ".py"
VENV_MARKER = "pyvenv.cfg"
SKIPPED_NAMES = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".eggs",
    }
)


class FileTooLarge(Exception):
    """A file is over the size limit."""


class NotRegularFile(OSError):
    """A path that was not a regular file when it was opened."""


class LimitReached(Exception):
    """A limit on the whole check was passed. It holds the reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SyntaxProblem:
    """A file that did not compile.

    The line is None when the parser gave none, or gave a line that is
    not a real line of the file.
    """

    name: str
    line: int | None
    message: str


@dataclass
class Report:
    """What a check of a project directory found."""

    checked: int = 0
    too_large: int = 0
    not_read: int = 0
    skipped_directories: int = 0
    total_bytes: int = 0
    problems: list[SyntaxProblem] = field(default_factory=list)


def _status_of(descriptor: int):
    """Return the status of an open file."""
    return os.fstat(descriptor)


def _open_flags() -> int:
    """Return the flags that open a file safely, as far as the system can.

    Binary mode matters on Windows, where text mode changes the bytes.
    No blocking and no following of a link are not there on every system.
    """
    flags = os.O_RDONLY

    for name in ("O_BINARY", "O_NONBLOCK", "O_NOFOLLOW"):
        flags |= getattr(os, name, 0)

    return flags


def read_python_file(path: str) -> bytes:
    """Read a regular file of at most MAX_FILE_BYTES bytes.

    Raises FileTooLarge for a bigger file, NotRegularFile for anything
    that is not a regular file, and OSError when the file cannot be read.
    The kind of file is that of the open descriptor, and not of the name,
    so a file that was swapped after it was listed is still caught.
    """
    descriptor = os.open(path, _open_flags())

    try:
        info = _status_of(descriptor)

        if not stat.S_ISREG(info.st_mode):
            raise NotRegularFile(f"not a regular file: {path}")

        if info.st_size > MAX_FILE_BYTES:
            raise FileTooLarge(path)

        chunks = []
        size = 0

        while True:
            chunk = os.read(descriptor, CHUNK_BYTES)

            if not chunk:
                break

            size += len(chunk)

            if size > MAX_FILE_BYTES:
                raise FileTooLarge(path)

            chunks.append(chunk)

        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _line_of(error: BaseException) -> int | None:
    """Return the line of an error when it is a real line of the file."""
    line = getattr(error, "lineno", None)

    if isinstance(line, int) and line >= 1:
        return line

    return None


def _message_of(error: BaseException) -> str:
    """Return the text of an error, or its type when it has none."""
    message = getattr(error, "msg", None)

    if isinstance(message, str) and message:
        return message

    if isinstance(error, SyntaxError):
        return type(error).__name__

    return str(error) or type(error).__name__


def compile_problem(name: str, data: bytes) -> SyntaxProblem | None:
    """Compile source and return the problem with it, if there is one.

    The code object is thrown away and never run. Every exception that
    the compiler raises is a problem with the file, whatever its type.
    """
    try:
        compile(data, "<file>", "exec", dont_inherit=True)
    except Exception as error:
        return SyntaxProblem(name, _line_of(error), _message_of(error))

    return None


def check_directory(root: Path | str) -> Report:
    """Walk a directory and check the Python files in it.

    The directory itself must be readable, and an OSError says why it is
    not. Anything below it that cannot be read is counted as not read.
    Raises LimitReached when the project is too big to check.
    """
    report = Report()
    found = 0
    pending = [("", os.fspath(root))]

    while pending:
        prefix, directory = pending.pop()

        try:
            with os.scandir(directory) as scan:
                children = list(scan)
        except OSError:
            if not prefix:
                raise

            report.not_read += 1
            continue

        if prefix and any(c.name.lower() == VENV_MARKER for c in children):
            report.skipped_directories += 1
            continue

        subdirectories = []

        for child in children:
            name = prefix + child.name

            try:
                info = child.stat(follow_symlinks=False)
            except OSError:
                report.not_read += 1
                continue

            python = child.name.endswith(PYTHON_SUFFIX)

            if is_link(info):
                report.not_read += python
                continue

            if stat.S_ISDIR(info.st_mode):
                if child.name.lower() in SKIPPED_NAMES:
                    report.skipped_directories += 1
                else:
                    subdirectories.append((name + "/", child.path))

                continue

            if not python:
                continue

            if not stat.S_ISREG(info.st_mode):
                report.not_read += 1
                continue

            found += 1

            if found > MAX_FILES:
                raise LimitReached(
                    f"too many Python files: more than {MAX_FILES}"
                )

            if info.st_size > MAX_FILE_BYTES:
                report.too_large += 1
                continue

            try:
                data = read_python_file(child.path)
            except FileTooLarge:
                report.too_large += 1
                continue
            except OSError:
                report.not_read += 1
                continue

            if report.total_bytes + len(data) > MAX_TOTAL_BYTES:
                raise LimitReached(
                    "too much Python code: more than "
                    f"{format_size(MAX_TOTAL_BYTES)}"
                )

            report.total_bytes += len(data)
            report.checked += 1
            problem = compile_problem(name, data)

            if problem is not None:
                report.problems.append(problem)

        pending.extend(subdirectories)

    report.problems.sort(key=lambda problem: problem.name)

    return report


def python_version() -> str:
    """Return the version of the Python that judges the files."""
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _shown(text: str, limit: int) -> str:
    """Return text that is safe to print and short, however it escapes."""
    shown = escape_name(text, limit=limit)
    cap = limit + limit // 2

    if len(shown) > cap:
        return shown[: cap - 3] + "..."

    return shown


def _problem_text(problem: SyntaxProblem) -> str:
    """Return one problem as a short text."""
    name = _shown(problem.name, NAME_LIMIT)
    message = _shown(problem.message, MESSAGE_LIMIT)

    if problem.line is None:
        return f"{name}: {message}"

    return f"{name} line {problem.line}: {message}"


def describe(report: Report) -> str:
    """Return a report as one short reason.

    It names the Python that judged the files, gives the counts, and shows
    the first few problems in the order of their names.
    """
    text = (
        f"checked Python syntax with Python {python_version()}: "
        f"{report.checked} files checked, "
        f"{len(report.problems)} with errors, "
        f"{report.too_large} too large, "
        f"{report.not_read} not read, "
        f"{report.skipped_directories} directories skipped"
    )

    if report.problems:
        shown = report.problems[:ERRORS_SHOWN]
        text += "; errors: " + "; ".join(_problem_text(p) for p in shown)

    return text
