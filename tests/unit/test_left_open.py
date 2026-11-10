"""Tests for closing an attempt that was left open for a final task."""

import os
from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from aic_control_centre.execution import run_lock
from aic_control_centre.execution.left_open import (
    LEFT_OPEN_REASON_PREFIX,
    ClosedLeftOpen,
    LeftOpenRefused,
    close_left_open_attempt,
)
from aic_control_centre.execution.records import (
    EXECUTION_SOURCE_CLI,
    EXECUTION_SOURCE_COORDINATOR,
    ExecutionRecord,
    ExecutionRecordRegistry,
)
from aic_control_centre.execution.run_lock import (
    OWNER_GONE,
    OWNER_UNKNOWN,
    RUN_LOCK_SUFFIX,
    RUNS_DIR_NAME,
    hold_run_lock,
)
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks import running
from aic_control_centre.tasks.registry import TaskRegistry


def _world(tmp_path):
    goals = GoalRegistry(tmp_path / "goals.json")
    tasks = TaskRegistry(tmp_path / "tasks.json")
    records = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")
    goal = Goal.create(description="Left open goal", project="TestProject")
    goals.add_goal(goal)

    return goals, tasks, records, goal


_PATHS = {
    "pending": [],
    "ready": ["ready"],
    "running": ["ready", "running"],
    "completed": ["ready", "running", "completed"],
    "failed": ["ready", "running", "failed"],
}


def _task(tasks, goal, status):
    """Make a task that is in the given status."""
    task = Task.create(goal_id=goal.id, title=f"{status} task")
    tasks.add_task(task)

    for step in _PATHS[status]:
        tasks.update_task_status(task.id, step)

    return task


def _left_open(tmp_path, status="completed", source="cli"):
    """A task that finished and an attempt that nothing closed."""
    goals, tasks, records, goal = _world(tmp_path)
    task = _task(tasks, goal, status)
    attempt = records.open_attempt(task.id, source, None)

    return tasks, records, task, attempt


def _close(tmp_path, tasks, records, task, reason="the write failed", **kw):
    return close_left_open_attempt(
        tasks,
        records,
        task.id,
        reason,
        **kw,
    )


def _files(tmp_path):
    return {
        name: (tmp_path / name).read_bytes()
        for name in sorted(os.listdir(tmp_path))
        if os.path.isfile(tmp_path / name)
    }


def _free_lock_file(tmp_path, attempt_id):
    runs = tmp_path / RUNS_DIR_NAME
    runs.mkdir(exist_ok=True)
    (runs / (attempt_id + RUN_LOCK_SUFFIX)).write_bytes(b"")


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_the_attempt_gets_the_outcome_that_the_task_has(
    tmp_path,
    status,
) -> None:
    tasks, records, task, attempt = _left_open(tmp_path, status)

    result = _close(tmp_path, tasks, records, task)

    stored = records.list_attempts(task.id)

    assert isinstance(result, ClosedLeftOpen)
    assert len(stored) == 1
    assert stored[0] == result.record
    assert stored[0].id == attempt.id
    assert stored[0].ended_as == status
    assert stored[0].started_at == attempt.started_at
    assert stored[0].source == attempt.source
    assert stored[0].is_open is False


def test_a_task_id_with_spaces_around_it_closes_the_attempt_of_the_task(
    tmp_path,
) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)

    result = close_left_open_attempt(
        tasks,
        records,
        f"  {task.id} ",
        "why",
    )

    stored = records.list_attempts(task.id)

    assert [record.id for record in stored] == [attempt.id]
    assert stored[0] == result.record
    assert stored[0].is_open is False


def test_the_reason_is_stripped_and_marked(tmp_path) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)

    result = _close(tmp_path, tasks, records, task, reason="  disk was full ")

    assert LEFT_OPEN_REASON_PREFIX == "closed afterwards: "
    assert result.record.reason == "closed afterwards: disk was full"


def test_the_time_is_the_time_of_the_call(tmp_path) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)
    before = datetime.now(timezone.utc)

    result = _close(tmp_path, tasks, records, task)

    after = datetime.now(timezone.utc)
    ended = datetime.fromisoformat(result.record.ended_at)

    assert before <= ended <= after
    assert ended >= datetime.fromisoformat(attempt.started_at)


def test_a_coordinator_attempt_is_closed_the_same_way(tmp_path) -> None:
    tasks, records, task, attempt = _left_open(
        tmp_path,
        source=EXECUTION_SOURCE_COORDINATOR,
    )

    result = _close(tmp_path, tasks, records, task)

    assert result.record.source == EXECUTION_SOURCE_COORDINATOR
    assert result.record.ended_as == "completed"


def test_a_blank_reason_is_refused_before_anything_is_read(tmp_path) -> None:
    with pytest.raises(LeftOpenRefused, match="a reason is required"):
        close_left_open_attempt(
            TaskRegistry(tmp_path / "tasks.json"),
            ExecutionRecordRegistry.beside(tmp_path / "tasks.json"),
            "no-such-task",
            "   ",
        )

    assert os.listdir(tmp_path) == []


def test_an_unknown_task_is_refused(tmp_path) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)
    before = _files(tmp_path)

    with pytest.raises(LeftOpenRefused, match="task not found: nope"):
        close_left_open_attempt(tasks, records, "nope", "why")

    assert _files(tmp_path) == before


def test_a_running_task_is_refused_and_its_attempt_stays_open(
    tmp_path,
) -> None:
    tasks, records, task, attempt = _left_open(tmp_path, "running")
    before = _files(tmp_path)

    with pytest.raises(LeftOpenRefused) as refused:
        _close(tmp_path, tasks, records, task)

    assert str(refused.value) == (
        f"task {task.id} is running; finish it with aic task complete, "
        "aic task fail or aic task requeue."
    )
    assert _files(tmp_path) == before
    assert records.get_open_attempt(task.id) is not None


@pytest.mark.parametrize("status", ["pending", "ready"])
def test_a_task_that_is_not_final_is_refused(tmp_path, status) -> None:
    goals, tasks, records, goal = _world(tmp_path)
    task = Task.create(goal_id=goal.id, title="not final")
    tasks.add_task(task)

    if status == "ready":
        tasks.update_task_status(task.id, "ready")

    records.open_attempt(task.id, EXECUTION_SOURCE_CLI, None)
    before = _files(tmp_path)

    with pytest.raises(LeftOpenRefused) as refused:
        _close(tmp_path, tasks, records, task)

    assert str(refused.value) == (
        f"task {task.id} is {status}, so it is not final. The next aic "
        "task start closes a left-over attempt as abandoned."
    )
    assert _files(tmp_path) == before


def test_a_task_with_no_open_attempt_gets_no_record(tmp_path) -> None:
    goals, tasks, records, goal = _world(tmp_path)
    task = _task(tasks, goal, "completed")
    before = _files(tmp_path)

    with pytest.raises(LeftOpenRefused) as refused:
        _close(tmp_path, tasks, records, task)

    assert str(refused.value) == f"task {task.id} has no open attempt."
    assert _files(tmp_path) == before
    assert not os.path.lexists(tmp_path / "executions.json")


def test_a_task_whose_attempts_are_all_closed_gets_no_record(
    tmp_path,
) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)
    records.close_attempt(task.id, "completed", "done")
    before = _files(tmp_path)

    with pytest.raises(LeftOpenRefused, match="has no open attempt"):
        _close(tmp_path, tasks, records, task)

    assert _files(tmp_path) == before
    assert len(records.list_attempts(task.id)) == 1


def test_more_than_one_open_attempt_is_refused(tmp_path) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)
    second = ExecutionRecord(
        id="second-attempt",
        task_id=task.id,
        source=EXECUTION_SOURCE_CLI,
        target=None,
        started_at=attempt.started_at,
        ended_at=None,
        ended_as=None,
        reason="",
    )
    write_text_atomic(
        tmp_path / "executions.json",
        serialize_state_items(
            "executions",
            [asdict(attempt), asdict(second)],
        ),
    )
    before = _files(tmp_path)

    with pytest.raises(LeftOpenRefused) as refused:
        _close(tmp_path, tasks, records, task)

    assert "has 2 open attempts" in str(refused.value)
    assert "hand edit" in str(refused.value)
    assert _files(tmp_path) == before


def test_only_the_attempt_of_that_task_changes(tmp_path) -> None:
    goals, tasks, records, goal = _world(tmp_path)
    other = _task(tasks, goal, "running")
    records.open_attempt(other.id, EXECUTION_SOURCE_CLI, None)
    finished = _task(tasks, goal, "completed")
    records.open_attempt(finished.id, EXECUTION_SOURCE_CLI, None)
    other_before = records.list_attempts(other.id)
    tasks_before = (tmp_path / "tasks.json").read_bytes()

    _close(tmp_path, tasks, records, finished)

    assert records.list_attempts(other.id) == other_before
    assert records.get_open_attempt(other.id) is not None
    assert (tmp_path / "tasks.json").read_bytes() == tasks_before


def test_closing_twice_refuses_the_second_time_and_changes_nothing(
    tmp_path,
) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)

    _close(tmp_path, tasks, records, task)
    before = _files(tmp_path)

    with pytest.raises(LeftOpenRefused, match="has no open attempt"):
        _close(tmp_path, tasks, records, task, reason="again")

    assert _files(tmp_path) == before


def test_a_run_that_is_alive_is_refused_and_nothing_is_written(
    tmp_path,
) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)
    before = _files(tmp_path)

    with hold_run_lock(tmp_path, attempt.id):
        with pytest.raises(LeftOpenRefused) as refused:
            _close(tmp_path, tasks, records, task, data_dir=tmp_path)

        assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
            attempt.id + RUN_LOCK_SUFFIX,
        ]

    assert str(refused.value).startswith(
        f"the run of task {task.id} is still alive: "
    )
    assert str(refused.value).endswith("and then close the attempt.")
    assert _files(tmp_path) == before
    assert records.get_open_attempt(task.id) is not None


def test_the_lock_file_of_a_gone_owner_is_removed_after_the_close(
    tmp_path,
) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)
    _free_lock_file(tmp_path, attempt.id)
    _free_lock_file(tmp_path, "another-attempt")

    result = _close(tmp_path, tasks, records, task, data_dir=tmp_path)

    assert result.owner == OWNER_GONE
    assert result.record.ended_as == "completed"
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        "another-attempt" + RUN_LOCK_SUFFIX,
    ]


def test_an_unknown_owner_leaves_the_directory_alone(tmp_path) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)

    result = _close(tmp_path, tasks, records, task, data_dir=tmp_path)

    assert result.owner == OWNER_UNKNOWN
    assert not os.path.lexists(tmp_path / RUNS_DIR_NAME)


def test_without_a_data_directory_the_owner_is_not_asked(tmp_path) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)
    _free_lock_file(tmp_path, attempt.id)

    result = _close(tmp_path, tasks, records, task)

    assert result.owner == OWNER_UNKNOWN
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        attempt.id + RUN_LOCK_SUFFIX,
    ]


def test_a_lock_file_that_cannot_be_removed_does_not_stop_the_close(
    tmp_path,
    monkeypatch,
) -> None:
    tasks, records, task, attempt = _left_open(tmp_path)
    _free_lock_file(tmp_path, attempt.id)

    def refuse(path):
        raise PermissionError("in use")

    monkeypatch.setattr(run_lock.os, "remove", refuse)

    result = _close(tmp_path, tasks, records, task, data_dir=tmp_path)

    assert result.record.is_open is False
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        attempt.id + RUN_LOCK_SUFFIX,
    ]


def test_the_owner_is_read_again_before_it_is_called_gone(
    tmp_path,
    monkeypatch,
) -> None:
    """A run that ended while the owner was asked is not a gone owner."""
    tasks, records, task, attempt = _left_open(tmp_path)
    _free_lock_file(tmp_path, attempt.id)

    def closed_while_probing(data_dir, attempt_id):
        records.close_attempt(task.id, "completed", "done by the run")

        return OWNER_GONE

    monkeypatch.setattr(running, "probe_run_lock", closed_while_probing)

    with pytest.raises(LeftOpenRefused, match="has no open attempt"):
        _close(tmp_path, tasks, records, task, data_dir=tmp_path)

    assert len(records.list_attempts(task.id)) == 1
