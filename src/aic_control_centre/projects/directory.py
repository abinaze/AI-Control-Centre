"""Looking at a project directory without hiding why it cannot be used.

pathlib's exists() and is_dir() turn every error into "no" on some Python
versions, and they did so on Python 3.14 for Windows when this was checked.
A directory that is there but cannot be looked at for a moment would then be
reported as missing. This module asks the operating system once, with
os.stat, and tells a directory that is not there from one that cannot be
read, so the reason that a person sees is the real one.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

MISSING = "missing"
NOT_A_DIRECTORY = "not a directory"
UNREADABLE = "unreadable"


def directory_problem(path: Path) -> tuple[str, str] | None:
    """Return None if the path is a directory, or why it is not.

    The answer is a kind and a detail. The kind is MISSING when nothing is
    there, NOT_A_DIRECTORY when something else is, and UNREADABLE when the
    operating system refused for any other reason. The detail is the reason
    that the system gave, and is empty for the first two kinds. The path is
    only looked at, never opened.
    """
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return MISSING, ""
    except (OSError, ValueError) as error:
        return UNREADABLE, _why(error)

    if not stat.S_ISDIR(info.st_mode):
        return NOT_A_DIRECTORY, ""

    return None


def _why(error: Exception) -> str:
    """Return the reason that the system gave, or the name of the error."""
    if isinstance(error, OSError) and error.strerror:
        return error.strerror

    return type(error).__name__
