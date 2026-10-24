"""A snapshot of a directory tree, taken to see whether a run changed it.

A snapshot lists everything below a directory: files with their size,
modification time and content hash, directories, and links. It is used
before and after a run that is meant to leave the project as it was.

Rules that matter:

- A link is recorded with its target and never followed. A link that
  points outside the project, or back into it, adds nothing to the
  snapshot.
- A file that is not a regular file, such as a pipe, is listed and never
  opened, because opening it could block.
- A file or directory that cannot be read is recorded as unreadable. That
  is not an error: it is the same before and after, unless it changes.
- The content hash is part of the comparison because the modification time
  of a file can advance in coarse steps, so a rewrite made straight after a
  write may leave it unchanged.

Names are relative to the directory, with "/" between the parts.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

KIND_FILE = "file"
KIND_DIRECTORY = "directory"
KIND_LINK = "link"
KIND_OTHER = "other"

UNREADABLE = "unreadable"

CHUNK_BYTES = 1024 * 1024

# Windows marks symbolic links and junctions with these reparse tags.
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
IO_REPARSE_TAG_SYMLINK = 0xA000000C
LINK_REPARSE_TAGS = frozenset(
    {IO_REPARSE_TAG_MOUNT_POINT, IO_REPARSE_TAG_SYMLINK},
)


@dataclass(frozen=True)
class Entry:
    """What a snapshot holds about one name."""

    kind: str
    size: int = 0
    mtime_ns: int = 0
    digest: str = ""
    target: str = ""


@dataclass(frozen=True)
class Changes:
    """The names that differ between two snapshots, each list sorted."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        """Return True when anything differs."""
        return bool(self.added or self.removed or self.changed)


def is_link(info) -> bool:
    """Return True for a symbolic link, or a Windows link or junction."""
    if stat.S_ISLNK(info.st_mode):
        return True

    return getattr(info, "st_reparse_tag", 0) in LINK_REPARSE_TAGS


def file_digest(path: str) -> str:
    """Return the SHA-256 of a file, or UNREADABLE if it cannot be read."""
    digest = hashlib.sha256()

    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(CHUNK_BYTES)

                if not chunk:
                    break

                digest.update(chunk)
    except OSError:
        return UNREADABLE

    return digest.hexdigest()


def classify(path: str, info) -> Entry:
    """Return the entry for a path, given its status without links followed.

    Only a regular file is opened.
    """
    if is_link(info):
        try:
            target = os.readlink(path)
        except OSError:
            target = UNREADABLE

        return Entry(KIND_LINK, target=target)

    if stat.S_ISDIR(info.st_mode):
        return Entry(KIND_DIRECTORY)

    if stat.S_ISREG(info.st_mode):
        return Entry(
            KIND_FILE,
            size=info.st_size,
            mtime_ns=info.st_mtime_ns,
            digest=file_digest(path),
        )

    return Entry(
        KIND_OTHER,
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
    )


def take_snapshot(root: Path | str) -> dict[str, Entry]:
    """Return a snapshot of everything below a directory.

    The directory itself must be readable, and an OSError says why it is
    not. Anything below it that cannot be read is recorded as unreadable.
    """
    snapshot: dict[str, Entry] = {}
    pending = [("", os.fspath(root))]

    while pending:
        prefix, directory = pending.pop()

        try:
            with os.scandir(directory) as scan:
                children = list(scan)
        except OSError:
            if not prefix:
                raise

            snapshot[prefix[:-1]] = Entry(KIND_DIRECTORY, digest=UNREADABLE)
            continue

        for child in children:
            name = prefix + child.name

            try:
                info = child.stat(follow_symlinks=False)
            except OSError:
                snapshot[name] = Entry(KIND_OTHER, digest=UNREADABLE)
                continue

            entry = classify(child.path, info)
            snapshot[name] = entry

            if entry.kind == KIND_DIRECTORY:
                pending.append((name + "/", child.path))

    return snapshot


def compare_snapshots(
    before: dict[str, Entry],
    after: dict[str, Entry],
) -> Changes:
    """Return the names that were added, removed or changed."""
    return Changes(
        added=tuple(sorted(set(after) - set(before))),
        removed=tuple(sorted(set(before) - set(after))),
        changed=tuple(
            sorted(
                name
                for name in before
                if name in after and before[name] != after[name]
            ),
        ),
    )


def escape_name(name: str, limit: int = 80) -> str:
    """Return a name that is safe to print, shortened to a limit.

    Names come from the project, so they are data. Control characters and
    other characters that cannot be shown are written as escapes, and a
    backslash is doubled, so a name cannot hide text or move the cursor.
    """
    shown = name[:limit]
    parts = []

    for character in shown:
        if character == "\\":
            parts.append("\\\\")
        elif character.isprintable():
            parts.append(character)
        elif ord(character) <= 0xFF:
            parts.append("\\x%02x" % ord(character))
        elif ord(character) <= 0xFFFF:
            parts.append("\\u%04x" % ord(character))
        else:
            parts.append("\\U%08x" % ord(character))

    if len(name) > limit:
        parts.append("...")

    return "".join(parts)
