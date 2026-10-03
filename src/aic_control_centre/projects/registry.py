"""Persistent project registry for AI-Control-Centre."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from aic_control_centre.config import load_config
from aic_control_centre.storage import write_text_atomic


@dataclass(frozen=True)
class Project:
    """A registered local project."""

    name: str
    path: Path


class ProjectRegistry:
    """Manage the persistent local project registry."""

    def __init__(self, registry_path: Path | None = None) -> None:
        config = load_config()
        self.registry_path = registry_path or config.projects_file

    def _load(self) -> list[Project]:
        """Load registered projects from disk."""
        if not self.registry_path.exists():
            return []

        data = json.loads(self.registry_path.read_text(encoding="utf-8"))

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
            json.dumps(data, indent=2),
        )

    def list_projects(self) -> list[Project]:
        """Return all registered projects."""
        return self._load()

    def add_project(self, path: Path) -> Project:
        """Register a local project."""
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

        project = Project(
            name=resolved_path.name,
            path=resolved_path,
        )

        projects.append(project)
        self._save(projects)

        return project
