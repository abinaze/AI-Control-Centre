"""Tests for execution outcome recording."""

import json

import pytest

from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_COMPLETED,
    EXECUTION_OUTCOME_FAILED,
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
    ExecutionOutcomeResult,
)
from aic_control_centre.execution.records import (
    EXECUTION_SOURCE_COORDINATOR,
)
from aic_control_centre.goals.model import (
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    Goal,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    TASK_STATUS_READY,
    TASK_STATUS_RUNNING,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry


def build_recorder(tmp_path):
    """Build an outcome recorder backed by isolated registries."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    return (
        ExecutionOutcomeRecorder(
            task_registry=task_registry,
            goal_registry=goal_registry,
        ),
        goal_registry,
        task_registry,
    )


def create_running_task(tmp_path):
    """Create a running task with an active parent goal."""
    recorder, goal_registry, task_registry = build_recorder(tmp_path)

    goal = Goal.create(
        description="Execution outcome goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Running task",
    )
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, TASK_STATUS_READY)
    task_registry.update_task_status(task.id, TASK_STATUS_RUNNING)

    return recorder, goal_registry, task_registry, task, goal


def test_running_task_can_be_completed(tmp_path):
    """A running task can record a completed outcome."""
    recorder, goal_registry, task_registry, task, goal = (
        create_running_task(tmp_path)
    )

    result = recorder.record(
        ExecutionOutcome(
            task_id=task.id,
            outcome=EXECUTION_OUTCOME_COMPLETED,
        ),
    )

    updated_task = task_registry.get_task(task.id)
    updated_goal = goal_registry.get_goal(goal.id)

    assert result.task_id == task.id
    assert result.completed is True
    assert result.outcome == EXECUTION_OUTCOME_COMPLETED
    assert result.reason == "task execution completed"

    assert updated_task is not None
    assert updated_task.status == TASK_STATUS_COMPLETED

    assert updated_goal is not None
    assert updated_goal.status == GOAL_STATUS_COMPLETED


def test_running_task_can_be_failed(tmp_path):
    """A running task can record a failed outcome."""
    recorder, goal_registry, task_registry, task, goal = (
        create_running_task(tmp_path)
    )

    result = recorder.record(
        ExecutionOutcome(
            task_id=task.id,
            outcome=EXECUTION_OUTCOME_FAILED,
        ),
    )

    updated_task = task_registry.get_task(task.id)
    updated_goal = goal_registry.get_goal(goal.id)

    assert result.task_id == task.id
    assert result.completed is True
    assert result.outcome == EXECUTION_OUTCOME_FAILED
    assert result.reason == "task execution failed"

    assert updated_task is not None
    assert updated_task.status == TASK_STATUS_FAILED

    assert updated_goal is not None
    assert updated_goal.status == GOAL_STATUS_FAILED


def test_custom_reason_is_preserved(tmp_path):
    """A supplied execution reason is preserved."""
    recorder, _, task_registry, task, _ = create_running_task(tmp_path)

    result = recorder.record(
        ExecutionOutcome(
            task_id=task.id,
            outcome=EXECUTION_OUTCOME_FAILED,
            reason="executor reported a controlled failure",
        ),
    )

    assert result.completed is True
    assert result.reason == "executor reported a controlled failure"

    updated_task = task_registry.get_task(task.id)
    assert updated_task is not None
    assert updated_task.status == TASK_STATUS_FAILED


def test_pending_task_cannot_record_outcome(tmp_path):
    """A pending task cannot jump directly to an execution outcome."""
    recorder, goal_registry, task_registry = build_recorder(tmp_path)

    goal = Goal.create(
        description="Pending outcome goal",
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

    result = recorder.record(
        ExecutionOutcome(
            task_id=task.id,
            outcome=EXECUTION_OUTCOME_COMPLETED,
        ),
    )

    after = task_registry.get_task(task.id)

    assert result.completed is False
    assert result.reason == "task status is pending"
    assert after is not None
    assert after.status == TASK_STATUS_PENDING
    assert after.updated_at == before.updated_at


def test_ready_task_cannot_record_outcome(tmp_path):
    """A ready task cannot jump directly to an execution outcome."""
    recorder, goal_registry, task_registry = build_recorder(tmp_path)

    goal = Goal.create(
        description="Ready outcome goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Ready task",
    )
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, TASK_STATUS_READY)

    result = recorder.record(
        ExecutionOutcome(
            task_id=task.id,
            outcome=EXECUTION_OUTCOME_COMPLETED,
        ),
    )

    after = task_registry.get_task(task.id)

    assert result.completed is False
    assert result.reason == "task status is ready"
    assert after is not None
    assert after.status == TASK_STATUS_READY


def test_missing_task_cannot_record_outcome(tmp_path):
    """A missing task cannot record an execution outcome."""
    recorder, _, _ = build_recorder(tmp_path)

    result = recorder.record(
        ExecutionOutcome(
            task_id="missing-task",
            outcome=EXECUTION_OUTCOME_COMPLETED,
        ),
    )

    assert result.task_id == "missing-task"
    assert result.completed is False
    assert result.reason == "task not found"


def test_outcome_is_persisted(tmp_path):
    """The execution outcome is persisted to the task registry."""
    recorder, _, task_registry, task, _ = create_running_task(tmp_path)

    recorder.record(
        ExecutionOutcome(
            task_id=task.id,
            outcome=EXECUTION_OUTCOME_COMPLETED,
        ),
    )

    persisted = json.loads(
        task_registry.registry_path.read_text(encoding="utf-8"),
    )["tasks"]

    assert len(persisted) == 1
    assert persisted[0]["id"] == task.id
    assert persisted[0]["status"] == TASK_STATUS_COMPLETED


def test_execution_outcome_is_immutable():
    """Execution outcomes cannot be modified."""
    outcome = ExecutionOutcome(
        task_id="task-123",
        outcome=EXECUTION_OUTCOME_COMPLETED,
    )

    with pytest.raises(AttributeError):
        outcome.outcome = EXECUTION_OUTCOME_FAILED


def test_execution_outcome_result_is_immutable():
    """Execution outcome results cannot be modified."""
    result = ExecutionOutcomeResult(
        task_id="task-123",
        completed=True,
        outcome=EXECUTION_OUTCOME_COMPLETED,
        reason="completed",
    )

    with pytest.raises(AttributeError):
        result.completed = False


@pytest.mark.parametrize("task_id", ["", "   ", "\t"])
def test_execution_outcome_rejects_empty_task_id(task_id):
    """Execution outcomes require a task ID."""
    with pytest.raises(ValueError, match="task ID cannot be empty"):
        ExecutionOutcome(
            task_id=task_id,
            outcome=EXECUTION_OUTCOME_COMPLETED,
        )


@pytest.mark.parametrize("outcome", ["", "pending", "ready", "running"])
def test_execution_outcome_rejects_unknown_outcome(outcome):
    """Execution outcomes allow only completed or failed."""
    with pytest.raises(
        ValueError,
        match="unknown execution outcome",
    ):
        ExecutionOutcome(
            task_id="task-123",
            outcome=outcome,
        )


@pytest.mark.parametrize("task_id", ["", "   ", "\t"])
def test_execution_outcome_result_rejects_empty_task_id(task_id):
    """Execution outcome results require a task ID."""
    with pytest.raises(ValueError, match="task ID cannot be empty"):
        ExecutionOutcomeResult(
            task_id=task_id,
            completed=False,
            outcome=EXECUTION_OUTCOME_COMPLETED,
            reason="rejected",
        )


@pytest.mark.parametrize("outcome", ["", "pending", "ready", "running"])
def test_execution_outcome_result_rejects_unknown_outcome(outcome):
    """Execution outcome results allow only completed or failed."""
    with pytest.raises(
        ValueError,
        match="unknown execution outcome",
    ):
        ExecutionOutcomeResult(
            task_id="task-123",
            completed=False,
            outcome=outcome,
            reason="rejected",
        )


@pytest.mark.parametrize("reason", ["", "   ", "\t"])
def test_execution_outcome_result_rejects_empty_reason(reason):
    """Execution outcome results require a reason."""
    with pytest.raises(
        ValueError,
        match="execution outcome result reason cannot be empty",
    ):
        ExecutionOutcomeResult(
            task_id="task-123",
            completed=False,
            outcome=EXECUTION_OUTCOME_COMPLETED,
            reason=reason,
        )


def test_completed_outcome_closes_the_open_attempt(tmp_path):
    """A completed outcome closes the attempt the start opened."""
    recorder, _, _, task, _ = create_running_task(tmp_path)
    opened = recorder.record_registry.open_attempt(
        task.id,
        EXECUTION_SOURCE_COORDINATOR,
        "test",
    )

    recorder.record(
        ExecutionOutcome(
            task_id=task.id,
            outcome=EXECUTION_OUTCOME_COMPLETED,
            reason="all checks passed",
        ),
    )

    records = recorder.record_registry.list_attempts(task.id)

    assert len(records) == 1
    assert records[0].id == opened.id
    assert records[0].started_at == opened.started_at
    assert records[0].ended_as == "completed"
    assert records[0].ended_at is not None
    assert records[0].reason == "all checks passed"


def test_failed_outcome_keeps_its_reason(tmp_path):
    """A failed outcome stores the reason the adapter gave."""
    recorder, _, _, task, _ = create_running_task(tmp_path)
    recorder.record_registry.open_attempt(
        task.id,
        EXECUTION_SOURCE_COORDINATOR,
        "test",
    )

    recorder.record(
        ExecutionOutcome(
            task_id=task.id,
            outcome=EXECUTION_OUTCOME_FAILED,
            reason="execution adapter failed: disk full",
        ),
    )

    record = recorder.record_registry.list_attempts(task.id)[0]

    assert record.ended_as == "failed"
    assert record.reason == "execution adapter failed: disk full"


def test_outcome_without_reason_stores_an_empty_reason(tmp_path):
    """The default result text is not stored as if it were a reason."""
    recorder, _, _, task, _ = create_running_task(tmp_path)

    recorder.record(
        ExecutionOutcome(
            task_id=task.id,
            outcome=EXECUTION_OUTCOME_COMPLETED,
        ),
    )

    record = recorder.record_registry.list_attempts(task.id)[0]

    assert record.reason == ""


def test_outcome_for_a_task_without_a_record_writes_a_legacy_record(
    tmp_path,
):
    """A task running before records existed still gets its ending."""
    recorder, _, _, task, _ = create_running_task(tmp_path)

    recorder.record(
        ExecutionOutcome(
            task_id=task.id,
            outcome=EXECUTION_OUTCOME_FAILED,
            reason="lost worker",
        ),
    )

    records = recorder.record_registry.list_attempts(task.id)

    assert len(records) == 1
    assert records[0].started_at is None
    assert records[0].source == EXECUTION_SOURCE_COORDINATOR
    assert records[0].ended_as == "failed"


def test_rejected_outcome_writes_no_record(tmp_path):
    """An outcome for a task that is not running changes nothing."""
    recorder, goal_registry, task_registry = build_recorder(tmp_path)
    goal = Goal.create(description="Pending goal", project="TestProject")
    goal_registry.add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Pending task")
    task_registry.add_task(task)

    result = recorder.record(
        ExecutionOutcome(
            task_id=task.id,
            outcome=EXECUTION_OUTCOME_COMPLETED,
        ),
    )

    assert result.completed is False
    assert not (tmp_path / "executions.json").exists()


def test_failed_record_write_leaves_an_open_attempt(tmp_path, monkeypatch):
    """A crash after the task moved leaves an open record, not a lie."""
    recorder, _, task_registry, task, _ = create_running_task(tmp_path)
    recorder.record_registry.open_attempt(
        task.id,
        EXECUTION_SOURCE_COORDINATOR,
        "test",
    )

    def fail_close(*args, **kwargs):
        raise OSError("simulated crash")

    monkeypatch.setattr(recorder.record_registry, "close_attempt", fail_close)

    with pytest.raises(OSError, match="simulated crash"):
        recorder.record(
            ExecutionOutcome(
                task_id=task.id,
                outcome=EXECUTION_OUTCOME_COMPLETED,
            ),
        )

    assert task_registry.get_task(task.id).status == TASK_STATUS_COMPLETED
    assert recorder.record_registry.get_open_attempt(task.id) is not None
