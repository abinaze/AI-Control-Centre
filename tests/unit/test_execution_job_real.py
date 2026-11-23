"""Tests of the job object against real children, on Windows.

Each test returns early on a system that is not Windows, and then it
checks nothing. They were written from what a script on Windows saw (see
docs/EXECUTION_LIMITS_DESIGN.md), and a failure there may be a mistake of
the test and not of the code: read the message first.
"""

import os
import subprocess
import sys
import time

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.job import create_job
from aic_control_centre.execution.process import ProcessAdapter

REQUEST = ExecutionRequest(task_id="task-1", target="test")

BEAT_CHILD = """
import sys, time
end = time.time() + 90
while time.time() < end:
    with open(sys.argv[1], "w") as handle:
        handle.write(repr(time.time()))
    time.sleep(0.1)
"""

PARENT_CHILD = """
import subprocess, sys, time
time.sleep(1)
subprocess.Popen([sys.executable, "-B", "-c", sys.argv[3], sys.argv[2]])
end = time.time() + 90
while time.time() < end:
    with open(sys.argv[1], "w") as handle:
        handle.write(repr(time.time()))
    time.sleep(0.1)
"""

STRAGGLER_CHILD = """
import json, subprocess, sys, time
time.sleep(1)
subprocess.Popen(
    [sys.executable, "-B", "-c", sys.argv[2], sys.argv[1]],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
time.sleep(1)
print(json.dumps({"outcome": "completed", "reason": "done"}))
"""

ALLOCATE_CHILD = """
import json, time
time.sleep(0.5)
data = bytearray(300 * 1024 * 1024)
print(json.dumps({"outcome": "completed", "reason": "allocated"}))
"""


def _beat(path):
    for _ in range(10):
        try:
            with open(path) as handle:
                return float(handle.read())
        except (OSError, ValueError):
            time.sleep(0.05)

    return None


def _beating(path):
    """Return True if the heartbeat of a file moves within a second."""
    first = _beat(path)
    time.sleep(0.6)
    second = _beat(path)

    return first is not None and second is not None and second > first


def _until(test, seconds):
    deadline = time.time() + seconds

    while time.time() < deadline:
        if test():
            return True

        time.sleep(0.2)

    return False


def test_closing_the_job_stops_the_child(tmp_path) -> None:
    """A child in a job is gone soon after the job is closed."""
    if os.name != "nt":
        return

    beat = tmp_path / "beat"
    job = create_job()
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", BEAT_CHILD, str(beat)]
    )

    try:
        job.assign(child)

        assert _until(lambda: _beating(beat), 30)

        job.close()

        assert _until(lambda: child.poll() is not None, 15)
    finally:
        job.close()
        child.kill()
        child.wait(timeout=15)


def test_a_process_that_the_child_started_goes_with_it(tmp_path) -> None:
    """A process that starts after the child is in the job is in it too."""
    if os.name != "nt":
        return

    own = tmp_path / "own"
    other = tmp_path / "other"
    job = create_job()
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", PARENT_CHILD, str(own), str(other),
         BEAT_CHILD]
    )

    try:
        job.assign(child)

        assert _until(lambda: _beating(other), 40)

        job.close()

        assert _until(lambda: child.poll() is not None, 15)
        assert _until(lambda: not _beating(other), 15)
    finally:
        job.close()
        child.kill()
        child.wait(timeout=15)


def test_a_limit_of_memory_stops_a_child_that_asks_for_more(
    tmp_path,
) -> None:
    """300 MiB are refused under a limit of 100 MiB, and given without one."""
    if os.name != "nt":
        return

    results = {}

    for name, limit in (("limited", 100), ("free", None)):
        job = create_job(limit)
        child = subprocess.Popen(
            [sys.executable, "-B", "-c", ALLOCATE_CHILD],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            job.assign(child)
            out, _err = child.communicate(timeout=60)
        finally:
            job.close()

        results[name] = (child.returncode, b"allocated" in out)

    assert results["limited"][1] is False
    assert results["limited"][0] != 0
    assert results["free"] == (0, True)


def test_the_process_adapter_reports_a_child_that_hit_the_limit() -> None:
    """A limit gives a failed outcome, and no limit gives a run."""
    if os.name != "nt":
        return

    command = [sys.executable, "-B", "-c", ALLOCATE_CHILD]
    limited = ProcessAdapter(command, memory_limit_mib=100).execute(REQUEST)
    free = ProcessAdapter(command, memory_limit_mib=None).execute(REQUEST)

    assert limited.outcome == "failed"
    assert limited.reason.startswith("adapter exited with status")
    assert free.outcome == "completed"
    assert free.reason == "allocated"


def test_the_default_limit_does_not_stop_a_small_child() -> None:
    """A child that needs little runs under the default limit."""
    if os.name != "nt":
        return

    code = (
        "import json; "
        "print(json.dumps({'outcome': 'completed', 'reason': 'ok'}))"
    )
    adapter = ProcessAdapter([sys.executable, "-B", "-c", code])
    outcome = adapter.execute(REQUEST)

    assert outcome.outcome == "completed"
    assert outcome.reason == "ok"


def test_a_process_left_behind_by_a_finished_run_is_stopped(tmp_path) -> None:
    """After a normal exit, the job ends what the child left running."""
    if os.name != "nt":
        return

    beat = tmp_path / "beat"
    command = [
        sys.executable,
        "-B",
        "-c",
        STRAGGLER_CHILD,
        str(beat),
        BEAT_CHILD,
    ]

    outcome = ProcessAdapter(command).execute(REQUEST)

    assert outcome.outcome == "completed"
    assert _until(lambda: not _beating(beat), 20)
