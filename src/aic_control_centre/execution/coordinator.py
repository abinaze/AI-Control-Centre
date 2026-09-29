"""Coordinate the execution lifecycle."""

from __future__ import annotations

from typing import Protocol

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import (
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
    ExecutionOutcomeResult,
)
from aic_control_centre.execution.start import ExecutionStartResult, ExecutionStarter


class ExecutionAdapter(Protocol):
    """Boundary for the component that performs actual execution."""

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        """Execute a request and return its outcome."""
        ...


class ExecutionCoordinator:
    """Coordinate admission, start, execution, and outcome recording."""

    def __init__(
        self,
        starter: ExecutionStarter | None = None,
        outcome_recorder: ExecutionOutcomeRecorder | None = None,
    ) -> None:
        self.starter = starter or ExecutionStarter()
        self.outcome_recorder = outcome_recorder or ExecutionOutcomeRecorder()

    def coordinate(
        self,
        request: ExecutionRequest,
        adapter: ExecutionAdapter,
    ) -> ExecutionOutcomeResult | ExecutionStartResult:
        """Coordinate one execution request through its lifecycle."""
        start_result = self.starter.start(request)

        if not start_result.started:
            return start_result

        outcome = adapter.execute(request)

        return self.outcome_recorder.record(
            ExecutionOutcome(
                task_id=request.task_id,
                outcome=outcome.outcome,
                reason=outcome.reason,
            )
        )
