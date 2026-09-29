"""Execution admission for AI-Control-Centre."""

from __future__ import annotations

from aic_control_centre.execution.contract import (
    ExecutionRequest,
    ExecutionResult,
)
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator


class ExecutionAdmission:
    """Determine whether an execution request may cross the execution boundary."""

    def __init__(
        self,
        readiness_evaluator: TaskReadinessEvaluator | None = None,
    ) -> None:
        self.readiness_evaluator = (
            readiness_evaluator or TaskReadinessEvaluator()
        )

    def evaluate(self, request: ExecutionRequest) -> ExecutionResult:
        """Evaluate an execution request without executing or mutating state."""
        readiness = self.readiness_evaluator.evaluate(request.task_id)

        if not readiness.ready:
            return ExecutionResult(
                task_id=request.task_id,
                accepted=False,
                reason=readiness.reason,
            )

        return ExecutionResult(
            task_id=request.task_id,
            accepted=True,
            reason="task accepted for execution",
        )
