"""Persistent goal registry for AI-Control-Centre."""

from __future__ import annotations

from pathlib import Path

from aic_control_centre.config import load_config
from aic_control_centre.goals.model import Goal
from aic_control_centre.storage import (
    read_state_items,
    serialize_state_items,
    write_text_atomic,
)


class GoalRegistry:
    """Manage the persistent local goal registry."""

    def __init__(self, registry_path: Path | None = None) -> None:
        config = load_config()
        self.registry_path = registry_path or config.goals_file

    def _load(self) -> list[Goal]:
        """Load registered goals from disk."""
        if not self.registry_path.exists():
            return []

        data = read_state_items(self.registry_path, "goals")

        return [
            Goal(
                id=item["id"],
                description=item["description"],
                project=item["project"],
                status=item["status"],
                created_at=item["created_at"],
                updated_at=item["updated_at"],
            )
            for item in data
        ]

    def _save(self, goals: list[Goal]) -> None:
        """Persist registered goals to disk."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        data = [
            {
                "id": goal.id,
                "description": goal.description,
                "project": goal.project,
                "status": goal.status,
                "created_at": goal.created_at,
                "updated_at": goal.updated_at,
            }
            for goal in goals
        ]

        write_text_atomic(
            self.registry_path,
            serialize_state_items("goals", data),
        )

    def list_goals(self) -> list[Goal]:
        """Return all registered goals."""
        return self._load()

    def get_goal(self, goal_id: str) -> Goal | None:
        """Return a goal by ID, or None when it does not exist."""
        for goal in self._load():
            if goal.id == goal_id:
                return goal

        return None

    def add_goal(self, goal: Goal) -> Goal:
        """Persist a goal."""
        goals = self._load()

        for existing in goals:
            if existing.id == goal.id:
                return existing

        goals.append(goal)
        self._save(goals)

        return goal

    def update_goal(self, goal: Goal) -> Goal:
        """Replace and persist an existing goal."""
        goals = self._load()

        for index, existing in enumerate(goals):
            if existing.id != goal.id:
                continue

            goals[index] = goal
            self._save(goals)

            return goal

        raise ValueError(f"Goal not found: {goal.id}")
