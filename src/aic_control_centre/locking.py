"""An exclusive lock that keeps concurrent aic processes apart.

Every registry changes state by reading a whole file and writing it back.
Two processes that overlap can overwrite each other's changes without any
error. The CLI therefore holds one lock on the data directory for the whole
of a command, so commands run one after another.

The lock is an operating system file lock on a single byte of
``.aic.lock``: ``fcntl.flock`` on Unix-like systems and ``msvcrt.locking``
on Windows. The operating system releases it when the process ends, even if
the process is killed, so a crash cannot leave the tool locked. The file is
never deleted.

The lock is advisory. It keeps ``aic`` processes apart; it does nothing
about a person editing a state file by hand. It is not reliable on network
file systems.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

try:
    import fcntl
except ImportError:
    fcntl = None
    import msvcrt

LOCK_FILE_NAME = ".aic.lock"
DEFAULT_LOCK_TIMEOUT = 10.0
POLL_INTERVAL = 0.02

_held = False


class StateLockError(RuntimeError):
    """The state lock could not be taken."""


def _try_lock(handle: IO[bytes]) -> bool:
    """Try to lock the file without waiting; return whether it worked."""
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return False

    return True


def _unlock(handle: IO[bytes]) -> None:
    """Release the lock. Closing the file would release it as well."""
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        else:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextmanager
def state_lock(
    data_dir: Path,
    timeout: float | None = None,
) -> Iterator[None]:
    """Hold the exclusive state lock for the data directory.

    The data directory is created if it is missing. If another process
    holds the lock, this retries until the timeout (DEFAULT_LOCK_TIMEOUT
    when none is given) and then raises StateLockError without changing
    anything.

    A process takes the lock once. Taking it a second time in the same
    process is a programming error and raises StateLockError, rather than
    waiting for a lock the process already holds.
    """
    global _held

    if _held:
        raise StateLockError("the state lock is already held by this process")

    wait = DEFAULT_LOCK_TIMEOUT if timeout is None else timeout

    data_dir.mkdir(parents=True, exist_ok=True)
    handle = (data_dir / LOCK_FILE_NAME).open("a+b", buffering=0)

    try:
        deadline = time.monotonic() + wait

        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                raise StateLockError(
                    "another aic process is using the state files "
                    f"(waited {wait:g}s)."
                )

            time.sleep(POLL_INTERVAL)

        _held = True

        try:
            yield
        finally:
            _held = False
            _unlock(handle)
    finally:
        handle.close()
