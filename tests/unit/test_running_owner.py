"""Tests for what the running task report says about the owner of a run."""

import os
from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from aic_control_centre.execution import run_lock
from aic_control_centre.execution.records import (
    ExecutionRecord,
    ExecutionRecordRegistry,
)
from aic_control_centre.execution.run_lock import (
    OWNER_ALIVE,
    OWNER_GONE,
    OWNER_UNKNOWN,
    RUN_LOCK_SUFFIX,
    RUNS_DIR_NAME,
    hold_run_lock,
)
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks import running
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.tasks.running import (
    OWNER_ENDED,
    OWNER_TEXT,
    describe_running_tasks,
)

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
EARLIER = "2026-10-19T09:00:00+00:00"


def _task(task_id, status="running"):
    return Task(
        id=task_id,
        goal_id="goal-1",
        title=f"title {task_id}",
        description="",
        status=status,
        created_at="2026-10-01T00:00:00+00:00",
        updated_at=EARLIER,
    )


def _record(task_id, attempt_id, source="coordinator", target="noop"):
    return ExecutionRecord(
        id=attempt_id,
        task_id=task_id,
        source=source,
        target=target,
        started_at=EARLIER,
        ended_at=None,
        ended_as=None,
        reason="",
    )


def _state(tmp_path, tasks, records=()):
    write_text_atomic(
        tmp_path / "tasks.json",
        serialize_state_items("tasks", [asdict(task) for task in tasks]),
    )

    if records:
        write_text_atomic(
            tmp_path / "executions.json",
            serialize_state_items(
                "executions",
                [asdict(record) for record in records],
            ),
        )


def _describe(tmp_path, data_dir="given"):
    return describe_running_tasks(
        TaskRegistry(tmp_path / "tasks.json"),
        ExecutionRecordRegistry.beside(tmp_path / "tasks.json"),
        NOW,
        tmp_path if data_dir == "given" else data_dir,
    )


def _free_lock_file(tmp_path, attempt_id):
    runs = tmp_path / RUNS_DIR_NAME
    runs.mkdir(exist_ok=True)
    (runs / (attempt_id + RUN_LOCK_SUFFIX)).write_bytes(b"")


def test_the_four_answers_have_a_text_each() -> None:
    assert OWNER_ENDED == "ended"
    assert set(OWNER_TEXT) == {
        OWNER_ALIVE,
        OWNER_GONE,
        OWNER_UNKNOWN,
        OWNER_ENDED,
    }
    assert OWNER_TEXT[OWNER_ALIVE].startswith("alive (")
    assert OWNER_TEXT[OWNER_GONE].startswith("gone (")
    assert "its child may still be running" in OWNER_TEXT[OWNER_GONE]
    assert OWNER_TEXT[OWNER_UNKNOWN].startswith("unknown (")
    assert OWNER_TEXT[OWNER_ENDED].startswith("ended (")


def test_a_held_lock_makes_the_owner_alive(tmp_path) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])

    with hold_run_lock(tmp_path, "attempt-1"):
        rows = _describe(tmp_path)

    assert [row.owner for row in rows] == [OWNER_ALIVE]


def test_a_free_lock_file_and_an_open_attempt_make_the_owner_gone(
    tmp_path,
) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])
    _free_lock_file(tmp_path, "attempt-1")

    rows = _describe(tmp_path)

    assert [row.owner for row in rows] == [OWNER_GONE]


def test_no_lock_file_makes_the_owner_unknown(tmp_path) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])

    assert [row.owner for row in _describe(tmp_path)] == [OWNER_UNKNOWN]


def test_a_cli_attempt_has_no_owner(tmp_path) -> None:
    _state(
        tmp_path,
        [_task("t1")],
        [_record("t1", "attempt-1", source="cli", target=None)],
    )

    assert [row.owner for row in _describe(tmp_path)] == [OWNER_UNKNOWN]


def test_a_running_task_with_no_attempt_has_no_owner(tmp_path) -> None:
    _state(tmp_path, [_task("t1")])
    _free_lock_file(tmp_path, "attempt-1")

    assert [row.owner for row in _describe(tmp_path)] == [OWNER_UNKNOWN]


def test_without_a_data_directory_every_owner_is_unknown(tmp_path) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])
    _free_lock_file(tmp_path, "attempt-1")

    rows = _describe(tmp_path, data_dir=None)

    assert [row.owner for row in rows] == [OWNER_UNKNOWN]


def test_an_attempt_id_that_is_not_a_safe_file_name_is_unknown(
    tmp_path,
) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "../attempt")])

    assert [row.owner for row in _describe(tmp_path)] == [OWNER_UNKNOWN]


def test_each_task_gets_the_owner_of_its_own_attempt(tmp_path) -> None:
    _state(
        tmp_path,
        [_task("t1"), _task("t2"), _task("t3")],
        [
            _record("t1", "attempt-1"),
            _record("t2", "attempt-2"),
            _record("t3", "attempt-3", source="cli", target=None),
        ],
    )
    _free_lock_file(tmp_path, "attempt-2")

    with hold_run_lock(tmp_path, "attempt-1"):
        rows = _describe(tmp_path)

    owners = {row.task_id: row.owner for row in rows}

    assert owners == {
        "t1": OWNER_ALIVE,
        "t2": OWNER_GONE,
        "t3": OWNER_UNKNOWN,
    }


def test_a_run_that_ended_while_it_was_checked_is_not_called_gone(
    tmp_path,
    monkeypatch,
) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])
    records = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")

    def finished_while_probing(data_dir, attempt_id):
        records.close_attempt("t1", "completed", "done")

        return OWNER_GONE

    monkeypatch.setattr(running, "probe_run_lock", finished_while_probing)

    assert [row.owner for row in _describe(tmp_path)] == [OWNER_ENDED]


def test_a_run_that_was_started_again_is_not_called_gone(
    tmp_path,
    monkeypatch,
) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])
    records = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")

    def started_again_while_probing(data_dir, attempt_id):
        records.open_attempt("t1", "coordinator", "noop")

        return OWNER_GONE

    monkeypatch.setattr(running, "probe_run_lock", started_again_while_probing)

    assert [row.owner for row in _describe(tmp_path)] == [OWNER_ENDED]


def test_asking_changes_no_file_and_makes_no_directory(tmp_path) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])
    before = sorted(os.listdir(tmp_path))
    contents = {
        name: (tmp_path / name).read_bytes() for name in before
    }

    _describe(tmp_path)

    assert sorted(os.listdir(tmp_path)) == before
    assert {
        name: (tmp_path / name).read_bytes() for name in before
    } == contents
    assert not os.path.lexists(tmp_path / RUNS_DIR_NAME)


def test_asking_leaves_a_free_lock_file_where_it_was(tmp_path) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])
    _free_lock_file(tmp_path, "attempt-1")

    _describe(tmp_path)
    _describe(tmp_path)

    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        "attempt-1" + RUN_LOCK_SUFFIX,
    ]
    assert run_lock.probe_run_lock(tmp_path, "attempt-1") == OWNER_GONE


@pytest.mark.parametrize("answer", [OWNER_ALIVE, OWNER_UNKNOWN])
def test_only_a_gone_answer_is_read_again(
    tmp_path,
    monkeypatch,
    answer,
) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])

    def closed_and_answering(data_dir, attempt_id):
        ExecutionRecordRegistry.beside(
            tmp_path / "tasks.json",
        ).close_attempt("t1", "completed", "done")

        return answer

    monkeypatch.setattr(running, "probe_run_lock", closed_and_answering)

    assert [row.owner for row in _describe(tmp_path)] == [answer]
