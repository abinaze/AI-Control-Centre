"""Read the request that AIC sends to an adapter module in a child process.

An adapter module that AIC ships and runs out of process answers every
request with one JSON line and exit status 0. The parts that every such
module needs are here, so that they are written once: decoding the
request, finding the project path in it, checking the directory, and
printing the answer. See aic_control_centre.execution.process for the
side that starts the child.

Rules that matter:

- A request that cannot be done is a failed outcome and never a crash.
- The path comes from the request, so it is data. It is escaped and cut
  before it goes into a reason.
- The check of the directory is given by the caller. The caller looks it
  up when it runs, so a test can replace it in the module of the child.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

from aic_control_centre.execution.snapshot import escape_name
from aic_control_centre.projects.directory import MISSING, NOT_A_DIRECTORY

PATH_LIMIT = 120

DirectoryCheck = Callable[[Path], tuple[str, str] | None]


def failed(reason: str) -> dict[str, str]:
    """Return the answer for a request that could not be done."""
    return {"outcome": "failed", "reason": reason}


class RequestRefused(Exception):
    """A request that cannot be done. It holds the reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    @property
    def outcome(self) -> dict[str, str]:
        """The failed outcome that answers the request."""
        return failed(self.reason)


def shown_path(path: str) -> str:
    """Return a path that is safe to put into a reason."""
    return escape_name(path, limit=PATH_LIMIT)


def read_project_path(request_bytes: bytes, check: DirectoryCheck) -> str:
    """Return the project path of a request, or raise RequestRefused.

    The request is UTF-8 JSON with a non-empty text under project_path.
    The check is called with the path and returns None when the directory
    can be used, and otherwise a kind and a detail.
    """
    try:
        text = request_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise RequestRefused("the request was not valid UTF-8") from None

    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        raise RequestRefused("the request was not valid JSON") from None

    path = data.get("project_path") if isinstance(data, dict) else None

    if not isinstance(path, str) or not path:
        raise RequestRefused("the request has no project path")

    shown = shown_path(path)
    problem = check(Path(path))

    if problem is None:
        return path

    kind, detail = problem

    if kind == MISSING:
        raise RequestRefused(f"the project directory does not exist: {shown}")

    if kind == NOT_A_DIRECTORY:
        raise RequestRefused(f"the project path is not a directory: {shown}")

    raise RequestRefused(
        f"the project directory cannot be read: {shown}; {detail}"
    )


def unreadable_outcome(error: OSError) -> dict[str, str]:
    """Return the answer for a project that failed while it was read."""
    reason = error.strerror or type(error).__name__

    return failed(
        f"the project directory cannot be read: "
        f"{escape_name(reason, limit=PATH_LIMIT)}"
    )


def serve(answer: Callable[[bytes], dict[str, str]]) -> int:
    """Read a request from standard input and print the answer as JSON."""
    print(json.dumps(answer(sys.stdin.buffer.read())))

    return 0
