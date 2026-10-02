"""Task readiness evaluation for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import dataclass

from aic_control_centre.goals.model import (
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    GOAL_STATUS_IN_PROGRESS,
    GOAL_STATUS_PENDING,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.model import TASK_STATUS_READY
from aic_control_centre.tasks.registry import TaskRegistry


KNOWN_GOAL_STATUSES = {
    GOAL_STATUS_PENDING,
    GOAL_STATUS_IN_PROGRESS,
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
}


@dataclass(frozen=True)
class TaskReadiness:
    """Read-only readiness result for a task."""

    task_id: str
    ready: bool
    reason: str


class TaskReadinessEvaluator:
    """Determine whether a persisted task is eligible for execution."""

    def __init__(
        self,
        goal_registry: GoalRegistry | None = None,
        task_registry: TaskRegistry | None = None,
    ) -> None:
        self.goal_registry = goal_registry or GoalRegistry()
        self.task_registry = task_registry or TaskRegistry()

    def evaluate(self, task_id: str) -> TaskReadiness:
        """Evaluate task readiness without modifying persisted state."""
        task = self.task_registry.get_task(task_id)

        if task is None:
            return TaskReadiness(
                task_id=task_id,
                ready=False,
                reason="task not found",
            )

        blocker = self.parent_goal_blocker(task.goal_id)

        if blocker is not None:
            return TaskReadiness(
                task_id=task.id,
                ready=False,
                reason=blocker,
            )

        if task.status != TASK_STATUS_READY:
            return TaskReadiness(
                task_id=task.id,
                ready=False,
                reason=f"task status is {task.status}",
            )

        return TaskReadiness(
            task_id=task.id,
            ready=True,
            reason="task is ready for execution",
        )

    def parent_goal_blocker(self, goal_id: str) -> str | None:
        """Return the reason a goal blocks execution, if any."""
        goal = self.goal_registry.get_goal(goal_id)

        if goal is None:
            return "parent goal not found"

        if goal.status not in KNOWN_GOAL_STATUSES:
            return f"parent goal has invalid status: {goal.status}"

        if goal.status == GOAL_STATUS_COMPLETED:
            return "parent goal is completed"

        if goal.status == GOAL_STATUS_FAILED:
            return "parent goal is failed"

        return None
