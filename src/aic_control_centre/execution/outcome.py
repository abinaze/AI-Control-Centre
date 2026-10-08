"""Execution outcome boundary for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import dataclass

from aic_control_centre.execution.records import (
    EXECUTION_SOURCE_COORDINATOR,
    ExecutionRecordRegistry,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.orchestration.goal_tasks import GoalTaskOrchestrator
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
)
from aic_control_centre.tasks.registry import TaskRegistry


EXECUTION_OUTCOME_COMPLETED = TASK_STATUS_COMPLETED
EXECUTION_OUTCOME_FAILED = TASK_STATUS_FAILED

KNOWN_EXECUTION_OUTCOMES = {
    EXECUTION_OUTCOME_COMPLETED,
    EXECUTION_OUTCOME_FAILED,
}


@dataclass(frozen=True)
class ExecutionOutcome:
    """Describe the final outcome of a running task."""

    task_id: str
    outcome: str
    reason: str = ""

    def __post_init__(self) -> None:
        """Reject incomplete execution outcomes."""
        if not self.task_id.strip():
            raise ValueError("task ID cannot be empty")

        if self.outcome not in KNOWN_EXECUTION_OUTCOMES:
            raise ValueError(
                f"unknown execution outcome: {self.outcome}"
            )


@dataclass(frozen=True)
class ExecutionOutcomeResult:
    """Describe the result of recording an execution outcome."""

    task_id: str
    completed: bool
    outcome: str
    reason: str

    def __post_init__(self) -> None:
        """Reject incomplete execution outcome results."""
        if not self.task_id.strip():
            raise ValueError("task ID cannot be empty")

        if self.outcome not in KNOWN_EXECUTION_OUTCOMES:
            raise ValueError(
                f"unknown execution outcome: {self.outcome}"
            )

        if not self.reason.strip():
            raise ValueError(
                "execution outcome result reason cannot be empty"
            )


class ExecutionOutcomeRecorder:
    """Record the final lifecycle outcome of a running task."""

    def __init__(
        self,
        task_registry: TaskRegistry | None = None,
        goal_registry: GoalRegistry | None = None,
        record_registry: ExecutionRecordRegistry | None = None,
    ) -> None:
        self.task_registry = task_registry or TaskRegistry()
        self.goal_registry = goal_registry or GoalRegistry()
        self.record_registry = (
            record_registry
            or ExecutionRecordRegistry.beside(
                self.task_registry.registry_path,
            )
        )
        self.orchestrator = GoalTaskOrchestrator(
            goal_registry=self.goal_registry,
            task_registry=self.task_registry,
        )

    def record(
        self,
        outcome: ExecutionOutcome,
    ) -> ExecutionOutcomeResult:
        """Record a completed or failed outcome for a running task.

        The task moves first and the attempt record is closed after it.
        A crash in between leaves an open record for a task that is no
        longer running, which is detectable.
        """
        task = self.task_registry.get_task(outcome.task_id)

        if task is None:
            return ExecutionOutcomeResult(
                task_id=outcome.task_id,
                completed=False,
                outcome=outcome.outcome,
                reason="task not found",
            )

        if task.status != TASK_STATUS_RUNNING:
            return ExecutionOutcomeResult(
                task_id=outcome.task_id,
                completed=False,
                outcome=outcome.outcome,
                reason=f"task status is {task.status}",
            )

        self.task_registry.update_task_status(
            task_id=outcome.task_id,
            new_status=outcome.outcome,
        )

        self.record_registry.close_attempt(
            task_id=outcome.task_id,
            ended_as=outcome.outcome,
            reason=outcome.reason,
            source=EXECUTION_SOURCE_COORDINATOR,
        )

        self.orchestrator.reconcile_goal(task.goal_id)

        reason = (
            outcome.reason.strip()
            or f"task execution {outcome.outcome}"
        )

        return ExecutionOutcomeResult(
            task_id=outcome.task_id,
            completed=True,
            outcome=outcome.outcome,
            reason=reason,
        )
