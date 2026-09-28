"""CLI commands for task management."""

from __future__ import annotations

from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.model import Task
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
