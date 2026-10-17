"""Execution admission for AI-Control-Centre."""

from __future__ import annotations

from aic_control_centre.execution.contract import (
    ExecutionRequest,
    ExecutionResult,
)
from aic_control_centre.execution.grants import GrantSource, NoGrants
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator


class ExecutionAdmission:
    """Determine whether an execution request may cross the execution boundary."""

    def __init__(
        self,
        readiness_evaluator: TaskReadinessEvaluator | None = None,
        grants: GrantSource | None = None,
    ) -> None:
        self.readiness_evaluator = (
            readiness_evaluator or TaskReadinessEvaluator()
        )
        self.grants = grants if grants is not None else NoGrants()

    def evaluate(self, request: ExecutionRequest) -> ExecutionResult:
        """Evaluate an execution request without executing or mutating state."""
        readiness = self.readiness_evaluator.evaluate(request.task_id)

        if not readiness.ready:
            return ExecutionResult(
                task_id=request.task_id,
                accepted=False,
                reason=readiness.reason,
            )

        if request.requires_grant:
            project = self._project_of(request.task_id)

            if not project or not self.grants.is_granted(
                project,
                request.target,
            ):
                return ExecutionResult(
                    task_id=request.task_id,
                    accepted=False,
                    reason=(
                        f"target {request.target} is not granted for "
                        f"project {project or 'unknown'}"
                    ),
                )

        return ExecutionResult(
            task_id=request.task_id,
            accepted=True,
            reason="task accepted for execution",
        )

    def _project_of(self, task_id: str) -> str:
        """Return the name of the project that a task belongs to."""
        task = self.readiness_evaluator.task_registry.get_task(task_id)

        if task is None:
            return ""

        goal = self.readiness_evaluator.goal_registry.get_goal(task.goal_id)

        if goal is None:
            return ""

        return goal.project
