"""CLI commands for goal management."""

from __future__ import annotations

from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.goals.archive import GoalArchive
from aic_control_centre.goals.archiving import GoalArchiveError, GoalArchiver
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.orchestration.goal_tasks import GoalTaskOrchestrator
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import Task
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


MAX_UNFINISHED_SHOWN = 5


def _print_unfinished(tasks: tuple[Task, ...]) -> None:
    """List the tasks that keep a goal from being archived."""
    if not tasks:
        return

    print(f"Tasks that are not finished: {len(tasks)}")

    for task in tasks[:MAX_UNFINISHED_SHOWN]:
        print(f"- {task.id} ({task.status})")

    hidden = len(tasks) - MAX_UNFINISHED_SHOWN

    if hidden > 0:
        print(f"  and {hidden} more")

    print("A goal can be archived when all of its tasks are finished.")


def archive_goal(goal_id: str, reason: str) -> int:
    """Move a finished goal, its tasks and their records to the archive."""
    tasks = TaskRegistry()
    archive = GoalArchive.beside(tasks.registry_path)
    archiver = GoalArchiver(
        goal_registry=GoalRegistry(),
        task_registry=tasks,
        record_registry=ExecutionRecordRegistry.beside(tasks.registry_path),
        archive=archive,
        project_registry=ProjectRegistry(),
    )

    try:
        result = archiver.archive_goal(goal_id.strip(), reason)
    except GoalArchiveError as exc:
        print(f"Error: {exc}")
        _print_unfinished(exc.unfinished)
        print("Nothing was changed.")
        return 1

    if result.already_done:
        print(f"Goal already archived: {result.goal_id}")
        print("Nothing was changed.")
        return 0

    if result.resumed:
        print(f"Goal archive finished: {result.goal_id}")
        print(
            "An earlier attempt had written the archive entry, "
            "and its reason is kept."
        )
    else:
        print(f"Goal archived: {result.goal_id}")

    print(f"Project: {result.project}")
    print(f"Project directory: {result.project_path or 'not recorded'}")
    print(f"Tasks archived: {result.tasks}")
    print(f"Execution records archived: {result.records}")
    print(f"Reason: {result.reason}")
    print(f"Archive: {archive.registry_path}")
    print("Nothing was deleted. The history is in the archive file.")

    return 0


def list_archived_goals() -> int:
    """List the goals that were archived. Nothing is changed."""
    archive = GoalArchive.beside(TaskRegistry().registry_path)
    entries = archive.list_entries()

    if not entries:
        print("No archived goals.")
        return 0

    print("Archived goals:")
    print()

    for entry in entries:
        goal = entry.goal

        print(f"- {goal.id}")
        print(f"  Project: {goal.project}")
        print(f"  Directory: {entry.project_path or 'not recorded'}")
        print(f"  Status: {goal.status}")
        print(f"  Description: {goal.description}")
        print(f"  Archived: {entry.archived_at}")
        print(f"  Reason: {entry.reason}")
        print(f"  Tasks: {len(entry.tasks)}")
        print(f"  Execution records: {len(entry.records)}")
        print()

    return 0
