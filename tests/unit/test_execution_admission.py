"""Tests for execution admission."""

from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.goals.model import (
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    Goal,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.tasks.model import TASK_STATUS_READY, Task
from aic_control_centre.tasks.registry import TaskRegistry


def build_admission(tmp_path):
    """Build an admission boundary backed by isolated registries."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")
    readiness_evaluator = TaskReadinessEvaluator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    )

    return (
        ExecutionAdmission(readiness_evaluator=readiness_evaluator),
        goal_registry,
        task_registry,
    )


def create_ready_task(tmp_path):
    """Create a ready task with an active parent goal."""
    admission, goal_registry, task_registry = build_admission(tmp_path)

    goal = Goal.create(
        description="Execution goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Ready task",
    )
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, TASK_STATUS_READY)

    return admission, goal_registry, task_registry, task


def create_task_with_goal_status(tmp_path, goal_status):
    """Create a ready task with a parent goal in the requested status."""
    admission, goal_registry, task_registry = build_admission(tmp_path)

    base_goal = Goal.create(
        description="Execution goal",
        project="TestProject",
    )
    goal = Goal(
        id=base_goal.id,
        description=base_goal.description,
        project=base_goal.project,
        status=goal_status,
        created_at=base_goal.created_at,
        updated_at=base_goal.updated_at,
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Ready task",
    )
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, TASK_STATUS_READY)

    return admission, goal_registry, task_registry, task


def test_ready_task_is_accepted(tmp_path):
    """A ready task crosses the admission boundary."""
    admission, _, _, task = create_ready_task(tmp_path)

    result = admission.evaluate(
        ExecutionRequest(task_id=task.id),
    )

    assert result.task_id == task.id
    assert result.accepted is True
    assert result.reason == "task accepted for execution"


def test_pending_task_is_rejected(tmp_path):
    """A pending task cannot cross the admission boundary."""
    admission, goal_registry, task_registry = build_admission(tmp_path)

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

    result = admission.evaluate(
        ExecutionRequest(task_id=task.id),
    )

    assert result.task_id == task.id
    assert result.accepted is False
    assert result.reason == "task status is pending"


def test_missing_task_is_rejected(tmp_path):
    """A missing task cannot cross the admission boundary."""
    admission, _, _ = build_admission(tmp_path)

    result = admission.evaluate(
        ExecutionRequest(task_id="missing-task"),
    )

    assert result.task_id == "missing-task"
    assert result.accepted is False
    assert result.reason == "task not found"


def test_orphan_task_is_rejected(tmp_path):
    """A task without a parent goal cannot cross the admission boundary."""
    admission, _, task_registry = build_admission(tmp_path)

    task = Task.create(
        goal_id="missing-goal",
        title="Orphan task",
    )
    task_registry.add_task(task)

    result = admission.evaluate(
        ExecutionRequest(task_id=task.id),
    )

    assert result.task_id == task.id
    assert result.accepted is False
    assert result.reason == "parent goal not found"


def test_completed_goal_rejects_ready_task(tmp_path):
    """A completed parent goal blocks execution admission."""
    admission, _, _, task = create_task_with_goal_status(
        tmp_path,
        GOAL_STATUS_COMPLETED,
    )

    result = admission.evaluate(
        ExecutionRequest(task_id=task.id),
    )

    assert result.task_id == task.id
    assert result.accepted is False
    assert result.reason == "parent goal is completed"


def test_admission_does_not_change_task_status(tmp_path):
    """Admission must not transition a ready task into running."""
    admission, _, task_registry, task = create_ready_task(tmp_path)

    before = task_registry.get_task(task.id)
    assert before is not None
    assert before.status == TASK_STATUS_READY

    result = admission.evaluate(
        ExecutionRequest(task_id=task.id),
    )

    after = task_registry.get_task(task.id)
    assert after is not None

    assert result.accepted is True
    assert after.status == TASK_STATUS_READY
    assert after.updated_at == before.updated_at


def test_admission_does_not_modify_persisted_task_file(tmp_path):
    """Admission must leave the persisted task registry unchanged."""
    admission, _, task_registry, task = create_ready_task(tmp_path)

    registry_path = task_registry.registry_path
    before = registry_path.read_text(encoding="utf-8")

    admission.evaluate(
        ExecutionRequest(task_id=task.id),
    )

    after = registry_path.read_text(encoding="utf-8")

    assert after == before


def test_failed_goal_rejects_ready_task(tmp_path):
    """A failed parent goal blocks execution admission."""
    admission, _, _, task = create_task_with_goal_status(
        tmp_path,
        GOAL_STATUS_FAILED,
    )

    result = admission.evaluate(
        ExecutionRequest(task_id=task.id),
    )

    assert result.task_id == task.id
    assert result.accepted is False
    assert result.reason == "parent goal is failed"


def test_invalid_goal_rejects_ready_task(tmp_path):
    """An invalid parent goal status blocks execution admission."""
    admission, _, _, task = create_task_with_goal_status(
        tmp_path,
        "corrupted",
    )

    result = admission.evaluate(
        ExecutionRequest(task_id=task.id),
    )

    assert result.task_id == task.id
    assert result.accepted is False
    assert result.reason == "parent goal has invalid status: corrupted"
