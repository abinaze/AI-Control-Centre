"""Persistent task registry for AI-Control-Centre."""

from __future__ import annotations

import json
from pathlib import Path

from aic_control_centre.config import load_config
from aic_control_centre.storage import write_text_atomic
from aic_control_centre.tasks.model import (
    Task,
    can_transition,
    utc_now,
)


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

        write_text_atomic(
            self.registry_path,
            json.dumps(data, indent=2),
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

    def list_tasks_for_goal(self, goal_id: str) -> list[Task]:
        """Return all tasks belonging to a goal."""
        return [
            task
            for task in self._load()
            if task.goal_id == goal_id
        ]

    def add_task(self, task: Task) -> Task:
        """Persist a task."""
        tasks = self._load()

        for existing in tasks:
            if existing.id == task.id:
                return existing

        tasks.append(task)
        self._save(tasks)

        return task

    def update_task_status(self, task_id: str, new_status: str) -> Task:
        """Update and persist a task status when the transition is valid."""
        tasks = self._load()

        for index, task in enumerate(tasks):
            if task.id != task_id:
                continue

            if not can_transition(task.status, new_status):
                raise ValueError(
                    f"Invalid task status transition: "
                    f"{task.status} -> {new_status}"
                )

            updated_task = Task(
                id=task.id,
                goal_id=task.goal_id,
                title=task.title,
                description=task.description,
                status=new_status,
                created_at=task.created_at,
                updated_at=utc_now(),
            )

            tasks[index] = updated_task
            self._save(tasks)

            return updated_task

        raise ValueError(f"Task not found: {task_id}")
