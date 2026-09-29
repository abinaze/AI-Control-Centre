"""Goal and task orchestration for AI-Control-Centre."""

from __future__ import annotations

from aic_control_centre.goals.model import (
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    GOAL_STATUS_IN_PROGRESS,
    GOAL_STATUS_PENDING,
    Goal,
    utc_now,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry


def derive_goal_status(tasks: list[Task]) -> str:
    """Derive a goal status from the lifecycle states of its tasks."""
    if not tasks:
        return GOAL_STATUS_PENDING

    if any(task.status == TASK_STATUS_FAILED for task in tasks):
        return GOAL_STATUS_FAILED

    if all(task.status == TASK_STATUS_COMPLETED for task in tasks):
        return GOAL_STATUS_COMPLETED

    return GOAL_STATUS_IN_PROGRESS


class GoalTaskOrchestrator:
    """Synchronize persisted goal state with its tasks."""

    def __init__(
        self,
        goal_registry: GoalRegistry | None = None,
        task_registry: TaskRegistry | None = None,
    ) -> None:
        self.goal_registry = goal_registry or GoalRegistry()
        self.task_registry = task_registry or TaskRegistry()

    def derive_status(self, goal_id: str) -> str:
        """Return the derived status for a goal without changing persistence."""
        goal = self.goal_registry.get_goal(goal_id)

        if goal is None:
            raise ValueError(f"Goal not found: {goal_id}")

        tasks = self.task_registry.list_tasks_for_goal(goal.id)

        return derive_goal_status(tasks)

    def reconcile_goal(self, goal_id: str) -> Goal:
        """Derive and persist the current status of a goal."""
        goal = self.goal_registry.get_goal(goal_id)

        if goal is None:
            raise ValueError(f"Goal not found: {goal_id}")

        tasks = self.task_registry.list_tasks_for_goal(goal.id)
        new_status = derive_goal_status(tasks)

        if goal.status == new_status:
            return goal

        updated_goal = Goal(
            id=goal.id,
            description=goal.description,
            project=goal.project,
            status=new_status,
            created_at=goal.created_at,
            updated_at=utc_now(),
        )

        self.goal_registry.update_goal(updated_goal)

        return updated_goal
