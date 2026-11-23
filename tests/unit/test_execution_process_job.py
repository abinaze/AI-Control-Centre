"""Tests for the job object in the process adapter, with a recording fake."""

import sys

import pytest

from aic_control_centre.execution import process as process_module
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.process import (
    DEFAULT_MEMORY_LIMIT_MIB,
    ProcessAdapter,
)

REQUEST = ExecutionRequest(task_id="task-1", target="test")

ECHO_CHILD = """
import json
print(json.dumps({"outcome": "completed", "reason": "ran"}))
"""
SLEEP_CHILD = "import time; time.sleep(60)"
FLOOD_CHILD = """
import sys
while True:
    sys.stdout.write("x" * 1000)
    sys.stdout.flush()
"""


class RecordingJob:
    """A job that records what is done with it, and whether the child
    had ended when it was closed."""

    def __init__(self, events, assign_fails=False):
        self._events = events
        self._assign_fails = assign_fails
        self._process = None

    def assign(self, process):
        self._events.append(("assign",))
        self._process = process

        if self._assign_fails:
            raise OSError("not in the job")

    def close(self):
        ended = self._process is None or self._process.poll() is not None
        self._events.append(("close", ended))


def _install(monkeypatch, assign_fails=False, make=None):
    """Replace create_job, and give back the list of events."""
    events = []

    def create(memory):
        events.append(("create", memory))

        if make is not None:
            return make()

        return RecordingJob(events, assign_fails)

    monkeypatch.setattr(process_module, "create_job", create)

    return events


def _adapter(code, **settings):
    return ProcessAdapter([sys.executable, "-c", code], **settings)


def test_the_default_memory_limit_is_512_mib() -> None:
    """The limit is of one process, and it can be set per adapter."""
    assert DEFAULT_MEMORY_LIMIT_MIB == 512
    assert ProcessAdapter(["python"]).memory_limit_mib == 512

    limited = ProcessAdapter(["python"], memory_limit_mib=64)
    unlimited = ProcessAdapter(["python"], memory_limit_mib=None)

    assert limited.memory_limit_mib == 64
    assert unlimited.memory_limit_mib is None


def test_the_memory_limit_must_be_greater_than_zero() -> None:
    """A zero or negative limit is refused when the adapter is built."""
    for limit in (0, -1, -0.5):
        with pytest.raises(ValueError):
            ProcessAdapter(["python"], memory_limit_mib=limit)


def test_a_run_makes_assigns_and_closes_a_job_in_that_order(
    monkeypatch,
) -> None:
    """The job is closed after the child has ended."""
    events = _install(monkeypatch)

    outcome = _adapter(ECHO_CHILD).execute(REQUEST)

    assert outcome.outcome == "completed"
    assert outcome.reason == "ran"
    assert events == [("create", 512), ("assign",), ("close", True)]


def test_the_limit_of_the_adapter_is_the_one_that_is_asked_for(
    monkeypatch,
) -> None:
    """A value, and None for no limit."""
    events = _install(monkeypatch)

    _adapter(ECHO_CHILD, memory_limit_mib=64).execute(REQUEST)
    _adapter(ECHO_CHILD, memory_limit_mib=None).execute(REQUEST)

    assert [e for e in events if e[0] == "create"] == [
        ("create", 64),
        ("create", None),
    ]


def test_the_job_is_closed_after_a_timeout(monkeypatch) -> None:
    """The child is stopped first, and then the job is closed."""
    events = _install(monkeypatch)

    outcome = _adapter(SLEEP_CHILD, timeout_seconds=0.5).execute(REQUEST)

    assert outcome.outcome == "failed"
    assert "timed out" in outcome.reason
    assert events == [("create", 512), ("assign",), ("close", True)]


def test_the_job_is_closed_after_too_much_output(monkeypatch) -> None:
    """The cap stops the child, and the job is closed after that."""
    events = _install(monkeypatch)

    outcome = _adapter(FLOOD_CHILD, stdout_limit=1000).execute(REQUEST)

    assert outcome.outcome == "failed"
    assert "output exceeded" in outcome.reason
    assert events == [("create", 512), ("assign",), ("close", True)]


def test_the_job_is_closed_after_an_interrupt(monkeypatch) -> None:
    """Ctrl-C reaches the finally block, which closes the job."""
    events = _install(monkeypatch)

    def interrupt(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(process_module, "_pause", interrupt)

    with pytest.raises(KeyboardInterrupt):
        _adapter(SLEEP_CHILD, timeout_seconds=60).execute(REQUEST)

    assert events == [("create", 512), ("assign",), ("close", True)]


def test_a_child_that_cannot_be_put_in_the_job_still_runs(
    monkeypatch,
) -> None:
    """The run goes on as before, and the job is closed once."""
    events = _install(monkeypatch, assign_fails=True)

    outcome = _adapter(ECHO_CHILD).execute(REQUEST)

    assert outcome.outcome == "completed"
    assert outcome.reason == "ran"
    assert [e[0] for e in events] == ["create", "assign", "close"]


def test_a_job_that_cannot_be_made_does_not_stop_the_run(
    monkeypatch,
) -> None:
    """An error of the system is not an error of the run."""
    def refuse():
        raise OSError("no job")

    events = _install(monkeypatch, make=refuse)

    outcome = _adapter(ECHO_CHILD).execute(REQUEST)

    assert outcome.outcome == "completed"
    assert events == [("create", 512)]


def test_no_job_is_a_run_as_before(monkeypatch) -> None:
    """None is what every system but Windows gives."""
    events = _install(monkeypatch, make=lambda: None)

    outcome = _adapter(ECHO_CHILD).execute(REQUEST)

    assert outcome.outcome == "completed"
    assert events == [("create", 512)]


def test_a_command_that_cannot_start_closes_the_job(monkeypatch) -> None:
    """The error is raised as before, and the job does not leak."""
    events = _install(monkeypatch)
    adapter = ProcessAdapter(["aic-no-such-command-for-the-test"])

    with pytest.raises(OSError):
        adapter.execute(REQUEST)

    assert events == [("create", 512), ("close", True)]


def test_a_real_run_is_the_same_without_a_job() -> None:
    """On a system that is not Windows, create_job gives back None."""
    outcome = _adapter(ECHO_CHILD).execute(REQUEST)

    assert outcome.outcome == "completed"
    assert outcome.reason == "ran"
