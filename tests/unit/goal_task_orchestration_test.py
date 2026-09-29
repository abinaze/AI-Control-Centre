"""Tests for goal and task orchestration."""

from aic_control_centre.goals.model import (
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    GOAL_STATUS_IN_PROGRESS,
    GOAL_STATUS_PENDING,
    Goal,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.orchestration.goal_tasks import (
    GoalTaskOrchestrator,
    derive_goal_status,
)
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    TASK_STATUS_READY,
    TASK_STATUS_RUNNING,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry


def make_task(status: str) -> Task:
    """Create a task with the requested status for testing."""
    task = Task.create(
        goal_id="goal-123",
        title="Test task",
    )

    return Task(
        id=task.id,
        goal_id=task.goal_id,
        title=task.title,
        description=task.description,
        status=status,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def test_empty_task_list_keeps_goal_pending() -> None:
    """A goal without tasks remains pending."""
    assert derive_goal_status([]) == GOAL_STATUS_PENDING


def test_incomplete_tasks_make_goal_in_progress() -> None:
    """Any non-terminal task makes the goal in progress."""
    for status in (
        TASK_STATUS_PENDING,
        TASK_STATUS_READY,
        TASK_STATUS_RUNNING,
    ):
        assert derive_goal_status([make_task(status)]) == GOAL_STATUS_IN_PROGRESS


def test_all_completed_tasks_complete_goal() -> None:
    """A goal completes when every task is completed."""
    tasks = [
        make_task(TASK_STATUS_COMPLETED),
        make_task(TASK_STATUS_COMPLETED),
    ]

    assert derive_goal_status(tasks) == GOAL_STATUS_COMPLETED


def test_any_failed_task_fails_goal() -> None:
    """A failed task makes the goal failed."""
    tasks = [
        make_task(TASK_STATUS_COMPLETED),
        make_task(TASK_STATUS_FAILED),
        make_task(TASK_STATUS_PENDING),
    ]

    assert derive_goal_status(tasks) == GOAL_STATUS_FAILED


def test_reconcile_goal_persists_derived_status(tmp_path) -> None:
    """Reconciling a goal persists the status derived from its tasks."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    goal_registry = GoalRegistry(goal_path)
    task_registry = TaskRegistry(task_path)

    goal = Goal.create(
        description="Test orchestration",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task_registry.add_task(
        Task.create(
            goal_id=goal.id,
            title="First task",
        )
    )

    orchestrator = GoalTaskOrchestrator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    )

    updated = orchestrator.reconcile_goal(goal.id)

    assert updated.status == GOAL_STATUS_IN_PROGRESS
    assert GoalRegistry(goal_path).get_goal(goal.id).status == GOAL_STATUS_IN_PROGRESS


def test_reconcile_completed_goal(tmp_path) -> None:
    """Reconciling completed tasks persists a completed goal."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    goal_registry = GoalRegistry(goal_path)
    task_registry = TaskRegistry(task_path)

    goal = Goal.create(
        description="Complete orchestration",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    for title in ("First task", "Second task"):
        task = Task.create(
            goal_id=goal.id,
            title=title,
        )
        completed = Task(
            id=task.id,
            goal_id=task.goal_id,
            title=task.title,
            description=task.description,
            status=TASK_STATUS_COMPLETED,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        task_registry.add_task(completed)

    orchestrator = GoalTaskOrchestrator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    )

    updated = orchestrator.reconcile_goal(goal.id)

    assert updated.status == GOAL_STATUS_COMPLETED


def test_reconcile_unknown_goal_fails(tmp_path) -> None:
    """Reconciling an unknown goal raises a clear error."""
    orchestrator = GoalTaskOrchestrator(
        goal_registry=GoalRegistry(tmp_path / "goals.json"),
        task_registry=TaskRegistry(tmp_path / "tasks.json"),
    )

    try:
        orchestrator.reconcile_goal("missing-goal")
    except ValueError as exc:
        assert str(exc) == "Goal not found: missing-goal"
    else:
        raise AssertionError("Expected ValueError")
