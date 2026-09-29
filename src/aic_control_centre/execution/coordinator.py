"""Coordinate the execution lifecycle."""

from __future__ import annotations

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_FAILED,
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
    ExecutionOutcomeResult,
)
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.start import ExecutionStartResult, ExecutionStarter


class ExecutionCoordinator:
    """Coordinate admission, start, adapter execution, and outcome recording."""

    def __init__(
        self,
        adapter_registry: ExecutionAdapterRegistry | None = None,
        starter: ExecutionStarter | None = None,
        outcome_recorder: ExecutionOutcomeRecorder | None = None,
    ) -> None:
        self.adapter_registry = adapter_registry or ExecutionAdapterRegistry()
        self.starter = starter or ExecutionStarter()
        self.outcome_recorder = outcome_recorder or ExecutionOutcomeRecorder()

    def coordinate(
        self,
        request: ExecutionRequest,
    ) -> ExecutionOutcomeResult | ExecutionStartResult:
        """Coordinate one execution request through its lifecycle."""
        adapter = self.adapter_registry.resolve(request.target)

        start_result = self.starter.start(request)

        if not start_result.started:
            return start_result
        try:
            outcome = adapter.execute(request)
        except Exception as exc:
            return self.outcome_recorder.record(
                ExecutionOutcome(
                    task_id=request.task_id,
                    outcome=EXECUTION_OUTCOME_FAILED,
                    reason=f"execution adapter failed: {exc}",
                )
            )

        return self.outcome_recorder.record(
            ExecutionOutcome(
                task_id=request.task_id,
                outcome=outcome.outcome,
                reason=outcome.reason,
            )
        )
