"""Tests for execution attempt records."""

import pytest

from aic_control_centre.execution.records import (
    ENDED_AS_COMPLETED,
    EXECUTION_SOURCE_CLI,
    EXECUTION_SOURCE_COORDINATOR,
    ExecutionRecord,
)


def _closed(**changes) -> ExecutionRecord:
    """Return a valid closed record, with the given fields replaced."""
    fields = {
        "id": "record-1",
        "task_id": "task-1",
        "source": EXECUTION_SOURCE_CLI,
        "target": None,
        "started_at": "2026-01-01T00:00:00+00:00",
        "ended_at": "2026-01-01T00:05:00+00:00",
        "ended_as": ENDED_AS_COMPLETED,
        "reason": "",
    }
    fields.update(changes)

    return ExecutionRecord(**fields)


def test_begin_creates_an_open_record() -> None:
    """A new record is open, has a start time, and has no ending."""
    record = ExecutionRecord.begin("task-1", EXECUTION_SOURCE_CLI)

    assert record.id
    assert record.task_id == "task-1"
    assert record.is_open
    assert record.started_at is not None
    assert record.ended_at is None
    assert record.ended_as is None
    assert record.reason == ""


def test_begin_keeps_the_source_and_target() -> None:
    """The route and the execution target are stored as given."""
    record = ExecutionRecord.begin(
        "task-1",
        EXECUTION_SOURCE_COORDINATOR,
        "test",
    )

    assert record.source == EXECUTION_SOURCE_COORDINATOR
    assert record.target == "test"


def test_begin_gives_each_record_its_own_id() -> None:
    """Two records never share an ID."""
    first = ExecutionRecord.begin("task-1", EXECUTION_SOURCE_CLI)
    second = ExecutionRecord.begin("task-1", EXECUTION_SOURCE_CLI)

    assert first.id != second.id


def test_closed_record_is_not_open() -> None:
    """A record with an ending is closed."""
    assert not _closed().is_open


@pytest.mark.parametrize("record_id", ["", "   "])
def test_record_rejects_empty_id(record_id) -> None:
    """A record needs an ID."""
    with pytest.raises(ValueError, match="record ID cannot be empty"):
        _closed(id=record_id)


@pytest.mark.parametrize("task_id", ["", "   "])
def test_record_rejects_empty_task_id(task_id) -> None:
    """A record needs a task ID."""
    with pytest.raises(ValueError, match="task ID cannot be empty"):
        _closed(task_id=task_id)


def test_record_rejects_unknown_source() -> None:
    """The source must be a known route."""
    with pytest.raises(ValueError, match="unknown execution source"):
        _closed(source="somewhere")


def test_record_rejects_unknown_end() -> None:
    """The ending must be a known one."""
    with pytest.raises(ValueError, match="unknown execution end"):
        _closed(ended_as="vanished")


@pytest.mark.parametrize(
    "changes",
    [{"ended_at": None}, {"ended_as": None}],
)
def test_record_rejects_half_an_ending(changes) -> None:
    """The end time and the ending are set together or not at all."""
    with pytest.raises(ValueError, match="must be set together"):
        _closed(**changes)


def test_open_record_needs_a_start_time() -> None:
    """An attempt that has not ended must say when it started."""
    with pytest.raises(ValueError, match="needs a start time"):
        _closed(started_at=None, ended_at=None, ended_as=None)


def test_closed_record_may_have_no_start_time() -> None:
    """A task that was running before records existed has no start."""
    record = _closed(started_at=None)

    assert record.started_at is None
    assert not record.is_open


def test_record_is_immutable() -> None:
    """A record cannot be changed after it is created."""
    record = _closed()

    with pytest.raises(AttributeError):
        record.reason = "changed"
