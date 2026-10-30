"""CLI commands for project management."""

from __future__ import annotations

from pathlib import Path

from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.registry import (
    Project,
    ProjectNameAmbiguousError,
    ProjectNameInUseError,
    ProjectNotRegisteredError,
    ProjectRegistry,
)
from aic_control_centre.projects.removal import (
    Blockers,
    removal_blockers,
)
from aic_control_centre.tasks.registry import TaskRegistry


def add_project(path: str) -> int:
    """Register a local project."""
    registry = ProjectRegistry()

    try:
        project = registry.add_project(Path(path))
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"Error: {exc}")
        return 1
    except ProjectNameInUseError as exc:
        print(f"Error: {exc}")
        print(
            "Project names must be unique, because goals and permissions "
            "use the name."
        )
        print("Rename one of the directories to register both.")
        return 1

    print(f"Project registered: {project.name}")
    print(f"Path: {project.path}")

    return 0


def list_projects() -> int:
    """List registered projects."""
    registry = ProjectRegistry()
    projects = registry.list_projects()

    if not projects:
        print("No projects registered.")
        return 0

    print("Registered projects:")
    print()

    for project in projects:
        print(f"- {project.name}")
        print(f"  Path: {project.path}")

    return 0


MAX_GOALS_SHOWN = 5


def _print_blockers(project: Project, blockers: Blockers) -> None:
    """Say what still uses a project, and what to do about it."""
    print(
        f"Error: project {project.name} cannot be removed, "
        "because it is still used."
    )

    if blockers.goals:
        print(f"Goals that use it: {len(blockers.goals)}")

        for goal in blockers.goals[:MAX_GOALS_SHOWN]:
            print(f"- {goal.id} ({goal.status})")

        hidden = len(blockers.goals) - MAX_GOALS_SHOWN

        if hidden > 0:
            print(f"  and {hidden} more")

    if blockers.grants:
        print(f"Active grants: {len(blockers.grants)}")

        for grant in blockers.grants:
            print(f"- target {grant.target}")

    print("Nothing was changed.")

    if blockers.goals:
        print(
            "Goals cannot be removed yet, so a project that has goals "
            "stays registered."
        )

    if blockers.grants:
        print(
            "Withdraw a grant with: "
            f"aic permission revoke {project.name} --target <target>"
        )


def remove_project(name: str, path: str | None = None) -> int:
    """Remove a project from the registry and leave its directory alone.

    A project that a goal or an active grant still names stays, because
    the removal would leave them pointing at a name that is not registered.
    """
    project_name = name.strip()

    if not project_name:
        print("Error: project name cannot be empty.")
        return 1

    registry = ProjectRegistry()

    try:
        project = registry.find_project(
            project_name,
            None if path is None else Path(path),
        )
    except ProjectNameAmbiguousError as exc:
        print(f"Error: {exc}")
        print(
            "Choose the one to remove with: "
            "aic project remove <name> --path <directory>"
        )
        return 1
    except ProjectNotRegisteredError as exc:
        print(f"Error: {exc}")
        return 1

    blockers = removal_blockers(
        project,
        registry.list_projects(),
        GoalRegistry().list_goals(),
        PermissionRegistry.beside(TaskRegistry().registry_path).list_grants(),
    )

    if blockers.found:
        _print_blockers(project, blockers)
        return 1

    registry.remove_project(project)

    print(f"Project removed: {project.name}")
    print(f"Path: {project.path}")
    print("The directory was not touched.")

    return 0
