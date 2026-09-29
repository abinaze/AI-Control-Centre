"""Coordinate the execution lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_COMPLETED,
    EXECUTION_OUTCOME_FAILED,
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
    ExecutionOutcomeResult,
)
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.start import ExecutionStarter


EXECUTION_COORDINATION_REJECTED = "rejected"
EXECUTION_COORDINATION_COMPLETED = "completed"
EXECUTION_COORDINATION_FAILED = "failed"

KNOWN_EXECUTION_COORDINATION_STATUSES = {
    EXECUTION_COORDINATION_REJECTED,
    EXECUTION_COORDINATION_COMPLETED,
    EXECUTION_COORDINATION_FAILED,
}


@dataclass(frozen=True)
class ExecutionCoordinateResult:
    """Describe the result of coordinating an execution request."""

    task_id: str
    status: str
    outcome: str | None
    reason: str

    def __post_init__(self) -> None:
        """Reject incomplete coordination results."""
        if not self.task_id.strip():
            raise ValueError("task ID cannot be empty")

        if self.status not in KNOWN_EXECUTION_COORDINATION_STATUSES:
            raise ValueError(
                f"unknown execution coordination status: {self.status}"
            )

        if not self.reason.strip():
            raise ValueError(
                "execution coordination result reason cannot be empty"
            )


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
    ) -> ExecutionCoordinateResult:
        """Coordinate one execution request through its lifecycle."""
        try:
            adapter = self.adapter_registry.resolve(request.target)
        except KeyError as exc:
            return ExecutionCoordinateResult(
                task_id=request.task_id,
                status=EXECUTION_COORDINATION_REJECTED,
                outcome=None,
                reason=str(exc).strip("'"),
            )

        start_result = self.starter.start(request)

        if not start_result.started:
            return ExecutionCoordinateResult(
                task_id=request.task_id,
                status=EXECUTION_COORDINATION_REJECTED,
                outcome=None,
                reason=start_result.reason,
            )

        try:
            outcome = adapter.execute(request)
        except Exception as exc:
            recorded = self.outcome_recorder.record(
                ExecutionOutcome(
                    task_id=request.task_id,
                    outcome=EXECUTION_OUTCOME_FAILED,
                    reason=f"execution adapter failed: {exc}",
                )
            )
            return self._from_recorded_outcome(recorded)

        if outcome.task_id != request.task_id:
            recorded = self.outcome_recorder.record(
                ExecutionOutcome(
                    task_id=request.task_id,
                    outcome=EXECUTION_OUTCOME_FAILED,
                    reason="execution adapter returned outcome for unexpected task",
                )
            )
            return self._from_recorded_outcome(recorded)

        recorded = self.outcome_recorder.record(
            ExecutionOutcome(
                task_id=outcome.task_id,
                outcome=outcome.outcome,
                reason=outcome.reason,
            )
        )

        return self._from_recorded_outcome(recorded)

    @staticmethod
    def _from_recorded_outcome(
        recorded: ExecutionOutcomeResult,
    ) -> ExecutionCoordinateResult:
        """Translate an outcome-recording result into the coordinator contract."""
        if not recorded.completed:
            return ExecutionCoordinateResult(
                task_id=recorded.task_id,
                status=EXECUTION_COORDINATION_REJECTED,
                outcome=None,
                reason=recorded.reason,
            )

        status = (
            EXECUTION_COORDINATION_COMPLETED
            if recorded.outcome == EXECUTION_OUTCOME_COMPLETED
            else EXECUTION_COORDINATION_FAILED
        )

        return ExecutionCoordinateResult(
            task_id=recorded.task_id,
            status=status,
            outcome=recorded.outcome,
            reason=recorded.reason,
        )
