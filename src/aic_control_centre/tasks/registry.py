"""Persistent task registry for AI-Control-Centre."""

from __future__ import annotations

import json
from pathlib import Path

from aic_control_centre.config import load_config
from aic_control_centre.tasks.model import Task


class TaskRegistry:
    """Manage the persistent local task registry."""

    def __init__(self, registry_path: Path | None = None) -> None:
        config = load_config()
        self.registry_path = registry_path or config.tasks_file

    def _load(self) -> list[Task]:
        """Load registered tasks from disk."""
        if not self.registry_path.exists():
            return []

        data = json.loads(self.registry_path.read_text(encoding="utf-8"))

        return [
            Task(
                id=item["id"],
                goal_id=item["goal_id"],
                title=item["title"],
                description=item["description"],
                status=item["status"],
                created_at=item["created_at"],
                updated_at=item["updated_at"],
            )
            for item in data
        ]

    def _save(self, tasks: list[Task]) -> None:
        """Persist registered tasks to disk."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        data = [
            {
                "id": task.id,
                "goal_id": task.goal_id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            }
            for task in tasks
        ]

        self.registry_path.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )

    def list_tasks(self) -> list[Task]:
        """Return all registered tasks."""
        return self._load()

    def get_task(self, task_id: str) -> Task | None:
        """Return a task by ID, or None when it does not exist."""
        for task in self._load():
            if task.id == task_id:
                return task

        return None

    def add_task(self, task: Task) -> Task:
        """Persist a task."""
        tasks = self._load()

        for existing in tasks:
            if existing.id == task.id:
                return existing

        tasks.append(task)
        self._save(tasks)

        return task
