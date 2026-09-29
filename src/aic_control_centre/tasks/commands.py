"""CLI commands for task management."""

from __future__ import annotations

from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.orchestration.goal_tasks import GoalTaskOrchestrator
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_READY,
    TASK_STATUS_RUNNING,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry


def create_task(goal_id: str, title: str) -> int:
    """Create and persist a new task for an existing goal."""
    if not goal_id.strip():
        print("Error: goal ID cannot be empty.")
        return 1

    if not title.strip():
        print("Error: task title cannot be empty.")
        return 1

    goal = GoalRegistry().get_goal(goal_id.strip())

    if goal is None:
        print(f"Error: goal not found: {goal_id}")
        return 1

    registry = TaskRegistry()

    task = Task.create(
        goal_id=goal.id,
        title=title.strip(),
    )

    registry.add_task(task)

    GoalTaskOrchestrator(
        goal_registry=GoalRegistry(),
        task_registry=registry,
    ).reconcile_goal(goal.id)

    print("Task created.")
    print(f"ID: {task.id}")
    print(f"Goal: {task.goal_id}")
    print(f"Status: {task.status}")
    print(f"Title: {task.title}")

    return 0


def list_tasks() -> int:
    """List all registered tasks."""
    registry = TaskRegistry()
    tasks = registry.list_tasks()

    if not tasks:
        print("No tasks registered.")
        return 0

    print("Registered tasks:")
    print()

    for task in tasks:
        print(f"- {task.id}")
        print(f"  Goal: {task.goal_id}")
        print(f"  Status: {task.status}")
        print(f"  Title: {task.title}")
        print(f"  Created: {task.created_at}")
        print()

    return 0


def show_task_status(task_id: str) -> int:
    """Show the status and details of a task."""
    registry = TaskRegistry()
    task = registry.get_task(task_id)

    if task is None:
        print(f"Error: task not found: {task_id}")
        return 1

    print(f"Task: {task.id}")
    print(f"Goal: {task.goal_id}")
    print(f"Status: {task.status}")
    print(f"Title: {task.title}")
    print(f"Description: {task.description}")
    print(f"Created: {task.created_at}")
    print(f"Updated: {task.updated_at}")

    return 0


def transition_task_status(task_id: str, new_status: str) -> int:
    """Transition a task to a requested lifecycle status."""
    if not task_id.strip():
        print("Error: task ID cannot be empty.")
        return 1

    registry = TaskRegistry()

    try:
        task = registry.update_task_status(
            task_id=task_id.strip(),
            new_status=new_status,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    GoalTaskOrchestrator(
        goal_registry=GoalRegistry(),
        task_registry=registry,
    ).reconcile_goal(task.goal_id)

    print("Task status updated.")
    print(f"ID: {task.id}")
    print(f"Status: {task.status}")

    return 0


def mark_task_ready(task_id: str) -> int:
    """Move a pending task to the ready state."""
    return transition_task_status(
        task_id=task_id,
        new_status=TASK_STATUS_READY,
    )


def start_task(task_id: str) -> int:
    """Move a ready task to the running state."""
    return transition_task_status(
        task_id=task_id,
        new_status=TASK_STATUS_RUNNING,
    )


def complete_task(task_id: str) -> int:
    """Move a running task to the completed state."""
    return transition_task_status(
        task_id=task_id,
        new_status=TASK_STATUS_COMPLETED,
    )


def fail_task(task_id: str) -> int:
    """Move a running task to the failed state."""
    return transition_task_status(
        task_id=task_id,
        new_status=TASK_STATUS_FAILED,
    )
