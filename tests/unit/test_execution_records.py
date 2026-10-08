"""Tests for execution attempt records."""

import json

import pytest

from aic_control_centre.execution.records import (
    ABANDONED_REASON,
    ENDED_AS_ABANDONED,
    ENDED_AS_COMPLETED,
    ENDED_AS_FAILED,
    ENDED_AS_REQUEUED,
    EXECUTION_SOURCE_CLI,
    EXECUTION_SOURCE_COORDINATOR,
    ExecutionRecord,
    ExecutionRecordRegistry,
)
from aic_control_centre.storage import (
    StateFileError,
    UnsupportedSchemaVersionError,
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


def _registry(tmp_path) -> ExecutionRecordRegistry:
    """Return a registry stored under the test directory."""
    return ExecutionRecordRegistry(tmp_path / "executions.json")


def _fail_replace(*args, **kwargs) -> None:
    """Simulate a crash while replacing the state file."""
    raise OSError("simulated crash")


def test_registry_starts_empty_without_creating_a_file(tmp_path) -> None:
    """Reading a missing file gives no records and creates nothing."""
    registry = _registry(tmp_path)

    assert registry.list_records() == []
    assert registry.list_attempts("task-1") == []
    assert registry.get_open_attempt("task-1") is None
    assert not registry.registry_path.exists()


def test_registry_beside_uses_the_task_file_directory(tmp_path) -> None:
    """The records file is stored next to the task registry file."""
    registry = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")

    assert registry.registry_path == tmp_path / "executions.json"


def test_open_attempt_persists_an_open_record(tmp_path) -> None:
    """Opening an attempt saves it in a versioned file."""
    registry = _registry(tmp_path)

    record = registry.open_attempt(
        "task-1",
        EXECUTION_SOURCE_COORDINATOR,
        "test",
    )

    data = json.loads(registry.registry_path.read_text(encoding="utf-8"))

    assert data["schema_version"] == 1
    assert [item["id"] for item in data["executions"]] == [record.id]
    assert data["executions"][0]["task_id"] == "task-1"
    assert data["executions"][0]["source"] == EXECUTION_SOURCE_COORDINATOR
    assert data["executions"][0]["target"] == "test"
    assert data["executions"][0]["ended_as"] is None
    assert registry.get_open_attempt("task-1") == record


def test_close_attempt_ends_the_open_record(tmp_path) -> None:
    """Closing an attempt stores its ending, time, and reason."""
    registry = _registry(tmp_path)
    opened = registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)

    closed = registry.close_attempt(
        "task-1",
        ENDED_AS_FAILED,
        "adapter crashed",
    )

    assert closed.id == opened.id
    assert closed.started_at == opened.started_at
    assert closed.ended_as == ENDED_AS_FAILED
    assert closed.ended_at is not None
    assert closed.reason == "adapter crashed"
    assert registry.list_attempts("task-1") == [closed]
    assert registry.get_open_attempt("task-1") is None


def test_close_attempt_strips_the_reason(tmp_path) -> None:
    """Whitespace around a reason is not stored."""
    registry = _registry(tmp_path)
    registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)

    closed = registry.close_attempt(
        "task-1",
        ENDED_AS_REQUEUED,
        "  worker died  ",
    )

    assert closed.reason == "worker died"


@pytest.mark.parametrize("ended_as", [ENDED_AS_ABANDONED, "vanished"])
def test_close_attempt_refuses_other_endings(tmp_path, ended_as) -> None:
    """Callers cannot close an attempt as abandoned or as unknown."""
    registry = _registry(tmp_path)
    registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)
    before = registry.registry_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="cannot close an attempt"):
        registry.close_attempt("task-1", ended_as)

    assert registry.registry_path.read_text(encoding="utf-8") == before


def test_close_attempt_without_open_record_writes_legacy_record(
    tmp_path,
) -> None:
    """A task running before records existed still gets its ending."""
    registry = _registry(tmp_path)

    closed = registry.close_attempt(
        "task-1",
        ENDED_AS_COMPLETED,
        source=EXECUTION_SOURCE_COORDINATOR,
    )

    assert closed.started_at is None
    assert closed.source == EXECUTION_SOURCE_COORDINATOR
    assert closed.ended_as == ENDED_AS_COMPLETED
    assert closed.ended_at is not None
    assert registry.list_attempts("task-1") == [closed]


def test_open_attempt_abandons_a_stale_open_record(tmp_path) -> None:
    """A record left open is closed as abandoned when a task restarts."""
    registry = _registry(tmp_path)
    first = registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)

    second = registry.open_attempt(
        "task-1",
        EXECUTION_SOURCE_COORDINATOR,
        "test",
    )

    records = registry.list_attempts("task-1")

    assert [record.id for record in records] == [first.id, second.id]
    assert records[0].ended_as == ENDED_AS_ABANDONED
    assert records[0].ended_at is not None
    assert records[0].reason == ABANDONED_REASON
    assert records[1].is_open
    assert registry.get_open_attempt("task-1") == second


def test_open_attempt_leaves_other_tasks_alone(tmp_path) -> None:
    """Abandoning a stale record never touches another task's record."""
    registry = _registry(tmp_path)
    other = registry.open_attempt("task-2", EXECUTION_SOURCE_CLI)

    registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)
    registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)

    assert registry.list_attempts("task-2") == [other]
    assert registry.get_open_attempt("task-2") == other


def test_list_attempts_returns_one_task_oldest_first(tmp_path) -> None:
    """Attempts are listed in the order they were made."""
    registry = _registry(tmp_path)
    first = registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)
    registry.close_attempt("task-1", ENDED_AS_REQUEUED, "died")
    registry.open_attempt("task-2", EXECUTION_SOURCE_CLI)
    second = registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)

    attempts = registry.list_attempts("task-1")

    assert [record.id for record in attempts] == [first.id, second.id]
    assert len(registry.list_records()) == 3


def test_failed_save_keeps_the_existing_file(tmp_path, monkeypatch) -> None:
    """A failed write leaves the previous records file intact."""
    registry = _registry(tmp_path)
    registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)
    before = registry.registry_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        "aic_control_centre.storage.os.replace",
        _fail_replace,
    )

    with pytest.raises(OSError, match="simulated crash"):
        registry.close_attempt("task-1", ENDED_AS_COMPLETED)

    assert registry.registry_path.read_text(encoding="utf-8") == before
    assert [path.name for path in tmp_path.iterdir()] == ["executions.json"]


def test_failed_open_keeps_the_stale_record_open(
    tmp_path,
    monkeypatch,
) -> None:
    """Abandoning and opening are one write, so both or neither happen."""
    registry = _registry(tmp_path)
    stale = registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)

    monkeypatch.setattr(
        "aic_control_centre.storage.os.replace",
        _fail_replace,
    )

    with pytest.raises(OSError, match="simulated crash"):
        registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)

    assert registry.list_attempts("task-1") == [stale]


def test_registry_refuses_newer_schema_version(tmp_path) -> None:
    """A file from a newer schema version is refused and left alone."""
    registry = _registry(tmp_path)
    text = json.dumps({"schema_version": 99, "executions": []})
    registry.registry_path.write_text(text, encoding="utf-8")

    with pytest.raises(UnsupportedSchemaVersionError):
        registry.list_records()

    with pytest.raises(UnsupportedSchemaVersionError):
        registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)

    with pytest.raises(UnsupportedSchemaVersionError):
        registry.close_attempt("task-1", ENDED_AS_COMPLETED)

    assert registry.registry_path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize(
    "item",
    [
        {"id": "record-1"},
        "not a record",
        {
            "id": "record-1",
            "task_id": "task-1",
            "source": "somewhere",
            "target": None,
            "started_at": "2026-01-01T00:00:00+00:00",
            "ended_at": None,
            "ended_as": None,
            "reason": "",
        },
    ],
)
def test_registry_reports_an_invalid_record(tmp_path, item) -> None:
    """A malformed record is a state file error, not a traceback."""
    registry = _registry(tmp_path)
    text = json.dumps({"schema_version": 1, "executions": [item]})
    registry.registry_path.write_text(text, encoding="utf-8")

    with pytest.raises(StateFileError, match="invalid execution record"):
        registry.list_records()

    assert registry.registry_path.read_text(encoding="utf-8") == text


def test_reading_does_not_rewrite_the_file(tmp_path) -> None:
    """Listing records never modifies the file."""
    registry = _registry(tmp_path)
    registry.open_attempt("task-1", EXECUTION_SOURCE_CLI)
    before = registry.registry_path.read_bytes()

    registry.list_records()
    registry.list_attempts("task-1")
    registry.get_open_attempt("task-1")

    assert registry.registry_path.read_bytes() == before
