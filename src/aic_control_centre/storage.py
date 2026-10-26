"""Crash-safe, versioned reading and writing of state files."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 1

# On Windows, replacing a file fails with a permission error while another
# process has it open. A short, bounded retry rides out a brief overlap.
REPLACE_ATTEMPTS = 5
REPLACE_RETRY_DELAY = 0.05


class StateFileError(ValueError):
    """A state file cannot be read as AI-Control-Centre state."""


class UnsupportedSchemaVersionError(StateFileError):
    """A state file was written by a newer schema version."""


def read_state_items(path: Path, collection: str) -> list[Any]:
    """Return the items stored in a state file.

    A versioned file is a JSON object with a schema_version number and a
    list of items under the collection name. A file written before
    versioning is a bare JSON list; it is read as schema version 1.

    Reading never modifies the file. A file written by a newer schema
    version than this one supports is refused rather than guessed at. A
    file that cannot be read is a StateFileError that says why. A file that
    is not there raises FileNotFoundError, which read_state_items_or_empty
    turns into an empty list.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        raise
    except OSError as exc:
        raise StateFileError(
            f"{path} cannot be read: {exc.strerror or type(exc).__name__}"
        ) from exc
    except ValueError as exc:
        raise StateFileError(f"{path} is not valid JSON: {exc}") from exc

    try:
        data = json.loads(text)
    except ValueError as exc:
        raise StateFileError(f"{path} is not valid JSON: {exc}") from exc

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        raise StateFileError(f"{path} must contain a JSON object or list")

    version = data.get("schema_version")

    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version < 1
    ):
        raise StateFileError(f"{path} has no valid schema_version")

    if version > SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            f"{path} uses schema version {version}, but this version of "
            f"AI-Control-Centre supports up to {SCHEMA_VERSION}"
        )

    items = data.get(collection)

    if not isinstance(items, list):
        raise StateFileError(f"{path} has no '{collection}' list")

    return items


def read_state_items_or_empty(path: Path, collection: str) -> list[Any]:
    """Return the items in a state file, or an empty list if it is absent.

    Only a file that is not there gives an empty list. Any other problem,
    such as a file that cannot be read for a moment, is an error. An empty
    list for such a file would let the next save write only the new item
    and overwrite everything that was saved. Path.exists() is not used,
    because on some Python versions it answers no for any error.
    """
    try:
        return read_state_items(path, collection)
    except (FileNotFoundError, NotADirectoryError):
        return []


def serialize_state_items(collection: str, items: list[Any]) -> str:
    """Return versioned JSON text for a state file."""
    return json.dumps(
        {"schema_version": SCHEMA_VERSION, collection: items},
        indent=2,
    )


def _replace_with_retry(source: Path, target: Path) -> None:
    """Move source over target, retrying after a permission error.

    Only PermissionError is retried, up to REPLACE_ATTEMPTS times. Any
    other error, and the last permission error, is raised.
    """
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS:
                raise

            time.sleep(REPLACE_RETRY_DELAY)


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
    lock. Concurrent aic processes are kept apart by the state lock
    that the command-line interface holds for each command.
    """
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")

    try:
        with temp_path.open("x", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        _replace_with_retry(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
