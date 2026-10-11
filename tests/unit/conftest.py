"""Shared fixtures for the unit tests."""

import subprocess
import sys

import pytest

_HOLDER_CODE = """
import sys
import time
from pathlib import Path

from aic_control_centre.locking import state_lock

with state_lock(Path(sys.argv[1])):
    print("locked", flush=True)
    time.sleep(float(sys.argv[2]))
"""


@pytest.fixture
def start_lock_holder():
    """Start a process that holds the state lock for a data directory.

    The returned function starts the process, waits until it holds the
    lock, and returns it. Every process is killed when the test ends.
    """
    holders = []

    def start(data_dir, seconds=60):
        process = subprocess.Popen(
            [sys.executable, "-c", _HOLDER_CODE, str(data_dir), str(seconds)],
            stdout=subprocess.PIPE,
            text=True,
        )
        holders.append(process)

        assert process.stdout.readline().strip() == "locked"

        return process

    yield start

    for process in holders:
        process.kill()
        process.wait()
        process.stdout.close()
