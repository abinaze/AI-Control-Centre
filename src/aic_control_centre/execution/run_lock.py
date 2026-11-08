"""A lock that shows whether the process that runs an attempt is alive.

A run that ``aic task run`` starts has an owner: the ``aic`` process that
runs the adapter and then records the outcome. While it works, the owner
holds an operating system lock on a small file named after the attempt. The
operating system releases that lock when the process ends, even when it is
killed, so another process can ask whether the owner is still there.

    alive    the lock cannot be taken, so the owner holds it
    gone     the file exists and the lock can be taken, so the owner ended
    unknown  there is no file, or it cannot be opened, so nothing is known

``gone`` means that the process that ran the attempt ended. It does not mean
that the work stopped, because the child of a process adapter starts in its
own process group and can outlive its owner.

A caller that finds ``gone`` must read the attempt again before it acts on
it. The owner closes the attempt before it releases the lock, so an attempt
that is still open after the lock was found free is proof. An attempt that
is closed ended normally.

The files live in a directory ``runs`` of the data directory. They are
empty and are never read. The owner removes its file when it ends normally.
A killed owner leaves its file behind.

This is the same kind of lock as the state lock, so it shares its limits:
it is advisory, and it is not reliable on network file systems.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# The same lock and unlock calls as the state lock, so that the platform
# differences between fcntl and msvcrt stay in one place.
from aic_control_centre.locking import _try_lock, _unlock

RUNS_DIR_NAME = "runs"
RUN_LOCK_SUFFIX = ".lock"
DEFAULT_HOLD_TIMEOUT = 1.0
POLL_INTERVAL = 0.02
MAX_ATTEMPT_ID_LENGTH = 100

OWNER_ALIVE = "alive"
OWNER_GONE = "gone"
OWNER_UNKNOWN = "unknown"

_SAFE_ATTEMPT_ID = re.compile(r"[A-Za-z0-9_-]+")


class RunLockError(RuntimeError):
    """The lock for an attempt could not be taken."""


def run_lock_path(data_dir: Path, attempt_id: str) -> Path:
    """Return the path of the lock file of an attempt.

    The id becomes a file name, so only letters, digits, hyphens and
    underscores are accepted, up to a fixed length. Any other id, such as
    one that a person wrote into a record by hand, could point outside the
    directory, and is refused.
    """
    if (
        len(attempt_id) > MAX_ATTEMPT_ID_LENGTH
        or _SAFE_ATTEMPT_ID.fullmatch(attempt_id) is None
    ):
        raise RunLockError(
            "the attempt ID cannot be used as a file name for a run lock"
        )

    return data_dir / RUNS_DIR_NAME / (attempt_id + RUN_LOCK_SUFFIX)


def _remove(path: Path) -> None:
    """Remove a lock file, and ignore a failure to do so.

    A file that stays behind is empty and harmless.
    """
    try:
        os.remove(path)
    except OSError:
        pass


@contextmanager
def hold_run_lock(
    data_dir: Path,
    attempt_id: str,
    timeout: float | None = None,
) -> Iterator[None]:
    """Hold the lock of an attempt while the caller runs it.

    The directory and the file are created if they are missing. If the lock
    is held for a moment by a process that is asking about it, this retries
    until the timeout (DEFAULT_HOLD_TIMEOUT when none is given). Any failure
    raises RunLockError before the body runs, so a caller can go on without
    an owner.

    The lock is released and the file is removed when the body ends,
    whether it ended normally or with an exception. The file of a lock that
    could not be taken is left alone, because it belongs to its holder.
    """
    path = run_lock_path(data_dir, attempt_id)
    wait = DEFAULT_HOLD_TIMEOUT if timeout is None else timeout

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+b", buffering=0)
    except OSError as exc:
        raise RunLockError(
            f"the run lock for attempt {attempt_id} cannot be made: {exc}"
        ) from exc

    locked = False

    try:
        deadline = time.monotonic() + wait

        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                raise RunLockError(
                    f"the run lock for attempt {attempt_id} is held by "
                    f"another process (waited {wait:g}s)"
                )

            time.sleep(POLL_INTERVAL)

        locked = True

        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()

        if locked:
            _remove(path)


def probe_run_lock(data_dir: Path, attempt_id: str) -> str:
    """Return whether the owner of an attempt is alive, gone or unknown.

    It never creates a file or a directory, and it never waits. A lock that
    it finds free is released again at once.
    """
    try:
        path = run_lock_path(data_dir, attempt_id)
        handle = path.open("r+b", buffering=0)
    except (RunLockError, OSError):
        return OWNER_UNKNOWN

    try:
        if not _try_lock(handle):
            return OWNER_ALIVE

        _unlock(handle)

        return OWNER_GONE
    finally:
        handle.close()


def remove_run_lock_file(data_dir: Path, attempt_id: str) -> None:
    """Remove the lock file that a killed owner left behind.

    Call it for an attempt whose owner is gone. A failure to remove the
    file is ignored, because a file that stays behind is empty and
    harmless, and so is an ID that is not a safe file name.
    """
    try:
        path = run_lock_path(data_dir, attempt_id)
    except RunLockError:
        return

    _remove(path)
