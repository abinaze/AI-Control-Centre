"""Coordinate the execution lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack, nullcontext
from dataclasses import dataclass, replace

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_COMPLETED,
    EXECUTION_OUTCOME_FAILED,
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
    ExecutionOutcomeResult,
)
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.run_lock import RunLockError
from aic_control_centre.execution.start import (
    ExecutionStarter,
    ExecutionStartResult,
)


# Returns a context manager that holds the state lock. The coordinator
# enters it around the start and around recording the outcome, and never
# around the adapter.
StateGuard = Callable[[], AbstractContextManager[None]]

# Returns a context manager that holds the run lock of an attempt, given
# the ID of the attempt. The coordinator enters it after the start and
# leaves it after the outcome is recorded, so that the lock shows that the
# process that runs the attempt is alive. It is entered outside the state
# guard, and it is never entered around the start.
RunGuard = Callable[[str], AbstractContextManager[None]]

NO_OWNER_NOTE = (
    "no owner was recorded for this run, so aic task running cannot tell "
    "whether it is alive"
)

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
    note: str | None = None

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

        if self.note is not None and not self.note.strip():
            raise ValueError(
                "execution coordination result note cannot be empty"
            )


class ExecutionCoordinator:
    """Coordinate admission, start, adapter execution, and outcome recording.

    A state guard, if given, is entered around the start and around each
    outcome recording, so another process cannot change the state files at
    the same time. It is never held while an adapter runs, so a person can
    still requeue a task during a long run. Without one the coordinator
    takes no lock, as before.

    An adapter that needs a project is given the registered path of its
    directory, found by admission. A path that a caller put in the request
    is never passed on.

    A run guard, if given, is entered after the start, with the ID of the
    attempt, and left after the outcome is recorded, also when the adapter
    raises or the recording fails. It is how the process that runs an
    attempt shows that it is alive. If it cannot be entered, the adapter
    runs anyway, and the result carries a note that says that no owner was
    recorded.
    """

    def __init__(
        self,
        adapter_registry: ExecutionAdapterRegistry | None = None,
        starter: ExecutionStarter | None = None,
        outcome_recorder: ExecutionOutcomeRecorder | None = None,
        state_guard: StateGuard | None = None,
        run_guard: RunGuard | None = None,
    ) -> None:
        self.adapter_registry = adapter_registry or ExecutionAdapterRegistry()
        self.starter = starter or ExecutionStarter()
        self.outcome_recorder = outcome_recorder or ExecutionOutcomeRecorder()
        self.state_guard = state_guard or nullcontext
        self.run_guard = run_guard

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

        start_request = replace(
            request,
            requires_grant=getattr(adapter, "requires_grant", True),
            requires_project=getattr(adapter, "requires_project", False),
        )

        with self.state_guard():
            start_result = self.starter.start(start_request)

        if not start_result.started:
            return ExecutionCoordinateResult(
                task_id=request.task_id,
                status=EXECUTION_COORDINATION_REJECTED,
                outcome=None,
                reason=start_result.reason,
            )

        note = None
        stack = ExitStack()

        if self.run_guard is not None and start_result.attempt_id is not None:
            try:
                stack.enter_context(self.run_guard(start_result.attempt_id))
            except RunLockError as exc:
                reason = " ".join(str(exc).split())
                note = f"{NO_OWNER_NOTE} ({reason})"

        with stack:
            result = self._execute_and_record(
                request,
                adapter,
                start_result,
            )

        if note is None:
            return result

        return replace(result, note=note)

    def _execute_and_record(
        self,
        request: ExecutionRequest,
        adapter,
        start_result: ExecutionStartResult,
    ) -> ExecutionCoordinateResult:
        """Run the adapter and record its outcome.

        The run lock of the attempt, if there is one, is held for all of
        it, so that the attempt is closed before the lock is released.
        """
        try:
            outcome = adapter.execute(
                replace(request, project_path=start_result.project_path),
            )
        except Exception as exc:
            recorded = self._record(
                ExecutionOutcome(
                    task_id=request.task_id,
                    outcome=EXECUTION_OUTCOME_FAILED,
                    reason=f"execution adapter failed: {exc}",
                    attempt_id=start_result.attempt_id,
                )
            )
            return self._from_recorded_outcome(recorded)

        if not isinstance(outcome, ExecutionOutcome):
            recorded = self._record(
                ExecutionOutcome(
                    task_id=request.task_id,
                    outcome=EXECUTION_OUTCOME_FAILED,
                    reason="execution adapter returned invalid outcome",
                    attempt_id=start_result.attempt_id,
                )
            )
            return self._from_recorded_outcome(recorded)

        if outcome.task_id != request.task_id:
            recorded = self._record(
                ExecutionOutcome(
                    task_id=request.task_id,
                    outcome=EXECUTION_OUTCOME_FAILED,
                    reason="execution adapter returned outcome for unexpected task",
                    attempt_id=start_result.attempt_id,
                )
            )
            return self._from_recorded_outcome(recorded)

        recorded = self._record(
            ExecutionOutcome(
                task_id=outcome.task_id,
                outcome=outcome.outcome,
                reason=outcome.reason,
                attempt_id=start_result.attempt_id,
            )
        )

        return self._from_recorded_outcome(recorded)

    def _record(self, outcome: ExecutionOutcome) -> ExecutionOutcomeResult:
        """Record an outcome while holding the state guard."""
        with self.state_guard():
            return self.outcome_recorder.record(outcome)

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
