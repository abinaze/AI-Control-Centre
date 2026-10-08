"""Execution start boundary for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import dataclass

from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.records import (
    EXECUTION_SOURCE_COORDINATOR,
    ExecutionRecordRegistry,
)
from aic_control_centre.tasks.model import TASK_STATUS_RUNNING
from aic_control_centre.tasks.registry import TaskRegistry


@dataclass(frozen=True)
class ExecutionStartResult:
    """Describe whether execution was successfully started."""

    task_id: str
    started: bool
    reason: str

    def __post_init__(self) -> None:
        """Reject incomplete execution start results."""
        if not self.task_id.strip():
            raise ValueError("task ID cannot be empty")

        if not self.reason.strip():
            raise ValueError("execution start result reason cannot be empty")


class ExecutionStarter:
    """Start an admitted task without executing its work."""

    def __init__(
        self,
        admission: ExecutionAdmission | None = None,
        task_registry: TaskRegistry | None = None,
        record_registry: ExecutionRecordRegistry | None = None,
    ) -> None:
        self.admission = admission or ExecutionAdmission()
        self.task_registry = task_registry or TaskRegistry()
        self.record_registry = (
            record_registry
            or ExecutionRecordRegistry.beside(
                self.task_registry.registry_path,
            )
        )

    def start(self, request: ExecutionRequest) -> ExecutionStartResult:
        """Start an admitted task by transitioning it to running.

        The attempt record is opened before the task moves to running. A
        crash in between leaves an open record and a ready task, which is
        detectable. The other order could leave a running task with no
        start time.
        """
        admission_result = self.admission.evaluate(request)

        if not admission_result.accepted:
            return ExecutionStartResult(
                task_id=request.task_id,
                started=False,
                reason=admission_result.reason,
            )

        self.record_registry.open_attempt(
            task_id=request.task_id,
            source=EXECUTION_SOURCE_COORDINATOR,
            target=request.target,
        )

        self.task_registry.update_task_status(
            request.task_id,
            TASK_STATUS_RUNNING,
        )

        return ExecutionStartResult(
            task_id=request.task_id,
            started=True,
            reason="task execution started",
        )
