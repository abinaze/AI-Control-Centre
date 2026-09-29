"""Coordinate the execution lifecycle."""

from __future__ import annotations

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import (
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
        start_result = self.starter.start(request)

        if not start_result.started:
            return start_result

        adapter = self.adapter_registry.resolve(request.target)
        outcome = adapter.execute(request)

        return self.outcome_recorder.record(
            ExecutionOutcome(
                task_id=request.task_id,
                outcome=outcome.outcome,
                reason=outcome.reason,
            )
        )
