"""Execution contract for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionRequest:
    """Describe a request to execute a persisted task."""

    task_id: str

    def __post_init__(self) -> None:
        """Reject requests without a task identifier."""
        if not self.task_id.strip():
            raise ValueError("task ID cannot be empty")


@dataclass(frozen=True)
class ExecutionResult:
    """Describe the outcome of an execution-boundary decision."""

    task_id: str
    accepted: bool
    reason: str

    def __post_init__(self) -> None:
        """Reject results without a task identifier or reason."""
        if not self.task_id.strip():
            raise ValueError("task ID cannot be empty")

        if not self.reason.strip():
            raise ValueError("execution result reason cannot be empty")
