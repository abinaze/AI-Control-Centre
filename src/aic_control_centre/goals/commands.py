"""CLI commands for goal management."""

from __future__ import annotations

from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.orchestration.goal_tasks import GoalTaskOrchestrator
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.registry import TaskRegistry


def create_goal(description: str, project: str) -> int:
    """Create and persist a new goal."""
    if not description.strip():
        print("Error: goal description cannot be empty.")
        return 1

    if not project.strip():
        print("Error: project cannot be empty.")
        return 1

    project_name = project.strip()

    if ProjectRegistry().get_project(project_name) is None:
        print(f"Error: project is not registered: {project_name}")
        print("Register it first with: aic project add <path>")
        return 1

    registry = GoalRegistry()
    goal = Goal.create(
        description=description.strip(),
        project=project_name,
    )
    registry.add_goal(goal)

    print("Goal created.")
    print(f"ID: {goal.id}")
    print(f"Project: {goal.project}")
    print(f"Status: {goal.status}")
    print(f"Description: {goal.description}")

    return 0


def list_goals() -> int:
    """List all registered goals."""
    registry = GoalRegistry()
    goals = registry.list_goals()

    if not goals:
        print("No goals registered.")
        return 0

    print("Registered goals:")
    print()

    for goal in goals:
        print(f"- {goal.id}")
        print(f"  Project: {goal.project}")
        print(f"  Status: {goal.status}")
        print(f"  Description: {goal.description}")
        print(f"  Created: {goal.created_at}")
        print()

    return 0


def show_goal_status(goal_id: str) -> int:
    """Show the status and details of a goal."""
    orchestrator = GoalTaskOrchestrator(
        goal_registry=GoalRegistry(),
        task_registry=TaskRegistry(),
    )

    try:
        goal = orchestrator.reconcile_goal(goal_id)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Goal: {goal.id}")
    print(f"Project: {goal.project}")
    print(f"Status: {goal.status}")
    print(f"Description: {goal.description}")
    print(f"Created: {goal.created_at}")
    print(f"Updated: {goal.updated_at}")

    return 0
