"""Crash-safe file writing for AI-Control-Centre state files."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4


def write_text_atomic(
    path: Path,
    text: str,
    encoding: str = "utf-8",
) -> None:
    """Replace a file's content so readers never see a partial write.

    The text is written to a temporary file in the same directory, flushed
    to disk, and then moved over the target with os.replace. If anything
    fails, the original file is left untouched and the temporary file is
    removed. The parent directory must already exist.

    This protects against a crash or error during a write. It is not a
    lock: concurrent writers can still overwrite each other's changes.
    """
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")

    try:
        with temp_path.open("x", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
