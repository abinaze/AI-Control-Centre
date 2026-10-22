"""CLI commands for project management."""

from __future__ import annotations

from pathlib import Path

from aic_control_centre.projects.registry import (
    ProjectNameInUseError,
    ProjectRegistry,
)


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
