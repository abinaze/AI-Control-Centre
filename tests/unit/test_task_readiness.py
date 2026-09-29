"""Tests for task readiness evaluation."""

from aic_control_centre.goals.model import (
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    Goal,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.tasks.model import (
    TASK_STATUS_READY,
    TASK_STATUS_RUNNING,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry


def test_missing_task_is_not_ready(tmp_path) -> None:
    """An unknown task cannot be ready."""
    evaluator = TaskReadinessEvaluator(
        goal_registry=GoalRegistry(tmp_path / "goals.json"),
        task_registry=TaskRegistry(tmp_path / "tasks.json"),
    )

    result = evaluator.evaluate("missing-task")

    assert result.ready is False
    assert result.task_id == "missing-task"
    assert result.reason == "task not found"


def test_orphan_task_is_not_ready(tmp_path) -> None:
    """A task without a parent goal cannot be ready."""
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    task = Task.create(
        goal_id="missing-goal",
        title="Orphan task",
    )
    task_registry.add_task(task)

    evaluator = TaskReadinessEvaluator(
        goal_registry=GoalRegistry(tmp_path / "goals.json"),
        task_registry=task_registry,
    )

    result = evaluator.evaluate(task.id)

    assert result.ready is False
    assert result.reason == "parent goal not found"


def test_pending_task_is_not_ready(tmp_path) -> None:
    """A pending task must first be moved to ready."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Readiness goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Pending task",
    )
    task_registry.add_task(task)

    result = TaskReadinessEvaluator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    ).evaluate(task.id)

    assert result.ready is False
    assert result.reason == "task status is pending"


def test_ready_task_is_ready(tmp_path) -> None:
    """A ready task with an active parent goal is executable."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Readiness goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Ready task",
    )
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, TASK_STATUS_READY)

    result = TaskReadinessEvaluator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    ).evaluate(task.id)

    assert result.ready is True
    assert result.reason == "task is ready for execution"


def test_running_task_is_not_ready(tmp_path) -> None:
    """A running task is no longer awaiting execution."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Readiness goal",
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

    result = TaskReadinessEvaluator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    ).evaluate(task.id)

    assert result.ready is False
    assert result.reason == "task status is running"


def test_completed_goal_blocks_ready_task(tmp_path) -> None:
    """A completed parent goal prevents task execution."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Completed goal",
        project="TestProject",
    )
    completed_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status=GOAL_STATUS_COMPLETED,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )
    goal_registry.add_goal(completed_goal)

    task = Task.create(
        goal_id=goal.id,
        title="Blocked task",
    )
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, TASK_STATUS_READY)

    result = TaskReadinessEvaluator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    ).evaluate(task.id)

    assert result.ready is False
    assert result.reason == "parent goal is completed"


def test_failed_goal_blocks_ready_task(tmp_path) -> None:
    """A failed parent goal prevents task execution."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Failed goal",
        project="TestProject",
    )
    failed_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status=GOAL_STATUS_FAILED,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )
    goal_registry.add_goal(failed_goal)

    task = Task.create(
        goal_id=goal.id,
        title="Blocked task",
    )
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, TASK_STATUS_READY)

    result = TaskReadinessEvaluator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    ).evaluate(task.id)

    assert result.ready is False
    assert result.reason == "parent goal is failed"



def test_invalid_goal_status_blocks_ready_task(tmp_path) -> None:
    """An invalid parent goal status must never become executable."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Invalid goal",
        project="TestProject",
    )
    invalid_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status="corrupted",
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )
    goal_registry.add_goal(invalid_goal)

    task = Task.create(
        goal_id=goal.id,
        title="Blocked task",
    )
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, TASK_STATUS_READY)

    result = TaskReadinessEvaluator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    ).evaluate(task.id)

    assert result.ready is False
    assert result.reason == "parent goal has invalid status: corrupted"
