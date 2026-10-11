"""Tests for the state lock."""

import subprocess
import sys

import pytest

from aic_control_centre.locking import (
    LOCK_FILE_NAME,
    StateLockError,
    state_lock,
)

_TRY_CODE = """
import sys
from pathlib import Path

from aic_control_centre.locking import StateLockError, state_lock

try:
    with state_lock(Path(sys.argv[1]), timeout=float(sys.argv[2])):
        print("acquired")
except StateLockError as exc:
    print(exc)
"""


def _try_in_another_process(data_dir, timeout):
    """Try to take the lock in a new process and return what it printed."""
    result = subprocess.run(
        [sys.executable, "-c", _TRY_CODE, str(data_dir), str(timeout)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    return result.stdout.strip()


def test_lock_creates_only_its_lock_file(tmp_path) -> None:
    """Taking the lock leaves one file behind and nothing else."""
    with state_lock(tmp_path):
        pass

    assert [path.name for path in tmp_path.iterdir()] == [LOCK_FILE_NAME]


def test_lock_creates_a_missing_data_directory(tmp_path) -> None:
    """The data directory is created if it does not exist yet."""
    data_dir = tmp_path / "nested" / "data"

    with state_lock(data_dir):
        assert (data_dir / LOCK_FILE_NAME).exists()


def test_lock_can_be_taken_again_after_release(tmp_path) -> None:
    """A released lock is free for the next holder."""
    with state_lock(tmp_path, timeout=1):
        pass

    with state_lock(tmp_path, timeout=1):
        pass


def test_lock_is_released_when_the_body_raises(tmp_path) -> None:
    """An error inside the lock does not leave it held."""
    with pytest.raises(ValueError, match="boom"):
        with state_lock(tmp_path):
            raise ValueError("boom")

    with state_lock(tmp_path, timeout=1):
        pass


def test_taking_the_lock_twice_in_one_process_is_an_error(tmp_path) -> None:
    """The same process never waits for a lock it already holds."""
    with state_lock(tmp_path):
        with pytest.raises(StateLockError, match="already held"):
            with state_lock(tmp_path):
                pass


def test_second_process_cannot_take_a_held_lock(
    tmp_path,
    start_lock_holder,
) -> None:
    """Another process gives up with a clear error and does not wait."""
    start_lock_holder(tmp_path)

    output = _try_in_another_process(tmp_path, 0.3)

    assert "another aic process is using the state files" in output
    assert "waited 0.3s" in output


def test_lock_is_released_when_the_holder_is_killed(
    tmp_path,
    start_lock_holder,
) -> None:
    """The operating system frees the lock when its holder dies."""
    holder = start_lock_holder(tmp_path)

    holder.kill()
    holder.wait()

    with state_lock(tmp_path, timeout=10):
        pass


def test_waiting_process_gets_the_lock_once_it_is_free(
    tmp_path,
    start_lock_holder,
) -> None:
    """A process that waits long enough takes over from the holder."""
    start_lock_holder(tmp_path, seconds=1.5)

    with pytest.raises(StateLockError, match=r"waited 0\.1s"):
        with state_lock(tmp_path, timeout=0.1):
            pass

    with state_lock(tmp_path, timeout=30):
        pass
