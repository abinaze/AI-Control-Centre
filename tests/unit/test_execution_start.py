"""Tests for execution start."""

import json

import pytest

from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.records import (
    ENDED_AS_ABANDONED,
    EXECUTION_SOURCE_CLI,
    EXECUTION_SOURCE_COORDINATOR,
)
from aic_control_centre.execution.start import (
    ExecutionStartResult,
    ExecutionStarter,
)
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.tasks.model import (
    TASK_STATUS_PENDING,
    TASK_STATUS_READY,
    TASK_STATUS_RUNNING,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry


def build_starter(tmp_path):
    """Build an execution starter backed by isolated registries."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")
    readiness_evaluator = TaskReadinessEvaluator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    )
    admission = ExecutionAdmission(
        readiness_evaluator=readiness_evaluator,
    )

    return (
        ExecutionStarter(
            admission=admission,
            task_registry=task_registry,
        ),
        goal_registry,
        task_registry,
    )


def create_ready_task(tmp_path):
    """Create a ready task with an active parent goal."""
    starter, goal_registry, task_registry = build_starter(tmp_path)

    goal = Goal.create(
        description="Execution start goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Ready task",
    )
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, TASK_STATUS_READY)

    return starter, task_registry, task


def test_ready_task_is_started(tmp_path):
    """A ready task transitions to running after admission."""
    starter, task_registry, task = create_ready_task(tmp_path)

    result = starter.start(
        ExecutionRequest(task_id=task.id, target="test"),
    )

    assert result.task_id == task.id
    assert result.started is True
    assert result.reason == "task execution started"

    updated_task = task_registry.get_task(task.id)
    assert updated_task is not None
    assert updated_task.status == TASK_STATUS_RUNNING


def test_pending_task_is_not_started(tmp_path):
    """A pending task is rejected before lifecycle mutation."""
    starter, goal_registry, task_registry = build_starter(tmp_path)

    goal = Goal.create(
        description="Pending goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Pending task",
    )
    task_registry.add_task(task)

    before = task_registry.get_task(task.id)
    assert before is not None
    assert before.status == TASK_STATUS_PENDING

    result = starter.start(
        ExecutionRequest(task_id=task.id, target="test"),
    )

    after = task_registry.get_task(task.id)
    assert after is not None

    assert result.started is False
    assert result.reason == "task status is pending"
    assert after.status == TASK_STATUS_PENDING
    assert after.updated_at == before.updated_at


def test_missing_task_is_not_started(tmp_path):
    """A missing task cannot be started."""
    starter, _, _ = build_starter(tmp_path)

    result = starter.start(
        ExecutionRequest(task_id="missing-task", target="test"),
    )

    assert result.task_id == "missing-task"
    assert result.started is False
    assert result.reason == "task not found"


def test_start_persists_running_status(tmp_path):
    """The running status is persisted by the task registry."""
    starter, task_registry, task = create_ready_task(tmp_path)

    starter.start(
        ExecutionRequest(task_id=task.id, target="test"),
    )

    persisted = json.loads(
        task_registry.registry_path.read_text(encoding="utf-8"),
    )["tasks"]

    assert len(persisted) == 1
    assert persisted[0]["id"] == task.id
    assert persisted[0]["status"] == TASK_STATUS_RUNNING


def test_execution_start_result_is_immutable():
    """Execution start results cannot be modified."""
    result = ExecutionStartResult(
        task_id="task-123",
        started=True,
        reason="task execution started",
    )

    with pytest.raises(AttributeError):
        result.started = False


@pytest.mark.parametrize("task_id", ["", "   ", "\t"])
def test_execution_start_result_rejects_empty_task_id(task_id):
    """Execution start results require a task ID."""
    with pytest.raises(ValueError, match="task ID cannot be empty"):
        ExecutionStartResult(
            task_id=task_id,
            started=False,
            reason="rejected",
        )


@pytest.mark.parametrize("reason", ["", "   ", "\t"])
def test_execution_start_result_rejects_empty_reason(reason):
    """Execution start results require a reason."""
    with pytest.raises(
        ValueError,
        match="execution start result reason cannot be empty",
    ):
        ExecutionStartResult(
            task_id="task-123",
            started=False,
            reason=reason,
        )


def test_started_task_opens_an_attempt_record(tmp_path):
    """Starting a task opens an attempt for it."""
    starter, _, task = create_ready_task(tmp_path)

    starter.start(ExecutionRequest(task_id=task.id, target="test"))

    records = starter.record_registry.list_attempts(task.id)

    assert len(records) == 1
    assert records[0].is_open
    assert records[0].source == EXECUTION_SOURCE_COORDINATOR
    assert records[0].target == "test"
    assert records[0].started_at is not None


def test_attempt_records_are_stored_beside_the_task_file(tmp_path):
    """The records file sits next to the task registry file."""
    starter, _, task = create_ready_task(tmp_path)

    starter.start(ExecutionRequest(task_id=task.id, target="test"))

    assert (tmp_path / "executions.json").exists()


def test_rejected_start_writes_no_attempt_record(tmp_path):
    """A rejected request changes no task and writes no record."""
    starter, _, _ = create_ready_task(tmp_path)

    result = starter.start(
        ExecutionRequest(task_id="missing-task", target="test"),
    )

    assert result.started is False
    assert not (tmp_path / "executions.json").exists()


def test_start_abandons_a_stale_open_attempt(tmp_path):
    """An attempt left open for a ready task is closed as abandoned."""
    starter, _, task = create_ready_task(tmp_path)
    starter.record_registry.open_attempt(task.id, EXECUTION_SOURCE_CLI)

    starter.start(ExecutionRequest(task_id=task.id, target="test"))

    records = starter.record_registry.list_attempts(task.id)

    assert [record.ended_as for record in records] == [
        ENDED_AS_ABANDONED,
        None,
    ]
    assert records[1].is_open


def test_failed_attempt_write_leaves_the_task_ready(tmp_path, monkeypatch):
    """If the record cannot be written, the task does not start."""
    starter, task_registry, task = create_ready_task(tmp_path)

    def fail_open(*args, **kwargs):
        raise OSError("simulated crash")

    monkeypatch.setattr(starter.record_registry, "open_attempt", fail_open)

    with pytest.raises(OSError, match="simulated crash"):
        starter.start(ExecutionRequest(task_id=task.id, target="test"))

    assert task_registry.get_task(task.id).status == TASK_STATUS_READY


def test_failed_task_update_leaves_an_open_attempt(tmp_path, monkeypatch):
    """A crash after the record leaves an open record and a ready task."""
    starter, task_registry, task = create_ready_task(tmp_path)

    def fail_update(*args, **kwargs):
        raise OSError("simulated crash")

    monkeypatch.setattr(task_registry, "update_task_status", fail_update)

    with pytest.raises(OSError, match="simulated crash"):
        starter.start(ExecutionRequest(task_id=task.id, target="test"))

    assert task_registry.get_task(task.id).status == TASK_STATUS_READY
    assert starter.record_registry.get_open_attempt(task.id) is not None
