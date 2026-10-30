"""Persistent project registry for AI-Control-Centre."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from aic_control_centre.config import load_config
from aic_control_centre.storage import (
    read_state_items_or_empty,
    serialize_state_items,
    write_text_atomic,
)


@dataclass(frozen=True)
class Project:
    """A registered local project."""

    name: str
    path: Path


class ProjectNameInUseError(ValueError):
    """Raised when another registered directory already has the name.

    Goals and permissions identify a project by its name, so two
    directories cannot share one.
    """

    def __init__(self, name: str, existing_path: Path) -> None:
        super().__init__(
            f"a project named {name} is already registered at "
            f"{existing_path}"
        )
        self.name = name
        self.existing_path = existing_path


class ProjectNotRegisteredError(ValueError):
    """Raised when no registered project has the name, or the directory."""

    def __init__(self, name: str, path: Path | None = None) -> None:
        if path is None:
            message = f"no project named {name} is registered"
        else:
            message = f"no project named {name} is registered at {path}"

        super().__init__(message)
        self.name = name
        self.path = path


class ProjectNameAmbiguousError(ValueError):
    """Raised when more than one registered directory has the name."""

    def __init__(self, name: str, paths: list[Path]) -> None:
        listed = ", ".join(str(path) for path in paths)

        super().__init__(f"{len(paths)} projects are named {name}: {listed}")
        self.name = name
        self.paths = paths


def _path_key(path: Path) -> str:
    """Return a string that is the same for the same directory.

    The path is resolved without needing the directory to exist, because
    the directory of a project may be the very thing that is gone.
    """
    return os.path.normcase(str(path.expanduser().resolve()))


class ProjectRegistry:
    """Manage the persistent local project registry."""

    def __init__(self, registry_path: Path | None = None) -> None:
        config = load_config()
        self.registry_path = registry_path or config.projects_file

    def _load(self) -> list[Project]:
        """Load registered projects from disk."""
        data = read_state_items_or_empty(
            self.registry_path,
            "projects",
        )

        return [
            Project(
                name=item["name"],
                path=Path(item["path"]),
            )
            for item in data
        ]

    def _save(self, projects: list[Project]) -> None:
        """Persist registered projects to disk."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        data = [
            {
                "name": project.name,
                "path": str(project.path),
            }
            for project in projects
        ]

        write_text_atomic(
            self.registry_path,
            serialize_state_items("projects", data),
        )

    def list_projects(self) -> list[Project]:
        """Return all registered projects."""
        return self._load()

    def add_project(self, path: Path) -> Project:
        """Register a local project.

        A directory that is registered already is returned as it is. A
        different directory with the same name as a registered project is
        refused, because a name must identify one directory.
        """
        resolved_path = path.expanduser().resolve()

        if not resolved_path.exists():
            raise FileNotFoundError(
                f"Project path does not exist: {resolved_path}"
            )

        if not resolved_path.is_dir():
            raise NotADirectoryError(
                f"Project path is not a directory: {resolved_path}"
            )

        projects = self._load()

        for project in projects:
            if project.path.resolve() == resolved_path:
                return project

        for project in projects:
            if project.name == resolved_path.name:
                raise ProjectNameInUseError(project.name, project.path)

        project = Project(
            name=resolved_path.name,
            path=resolved_path,
        )

        projects.append(project)
        self._save(projects)

        return project

    def get_project(self, name: str) -> Project | None:
        """Return the registered project with this exact name, if any."""
        for project in self._load():
            if project.name == name:
                return project

        return None

    def find_project(self, name: str, path: Path | None = None) -> Project:
        """Return the registered project that has this name.

        A name that more than one directory has does not say which one is
        meant, so it needs the directory too. The directory is compared as
        a resolved path and may be one that no longer exists. When the file
        holds the same entry twice, the directory picks one of them.
        """
        matches = [item for item in self._load() if item.name == name]

        if path is not None:
            wanted = _path_key(path)
            matches = [
                item for item in matches if _path_key(item.path) == wanted
            ]

            if not matches:
                raise ProjectNotRegisteredError(name, path)

            return matches[0]

        if not matches:
            raise ProjectNotRegisteredError(name)

        if len(matches) > 1:
            raise ProjectNameAmbiguousError(
                name,
                [item.path for item in matches],
            )

        return matches[0]

    def remove_project(self, project: Project) -> None:
        """Remove one registry entry. The directory is never touched.

        Only the entry that has this name and path is removed, and only one
        of them when the file holds the same entry twice. Whether anything
        still uses the project is for the caller to decide.
        """
        projects = self._load()

        for index, existing in enumerate(projects):
            if (
                existing.name == project.name
                and existing.path == project.path
            ):
                del projects[index]
                self._save(projects)

                return

        raise ProjectNotRegisteredError(project.name, project.path)
