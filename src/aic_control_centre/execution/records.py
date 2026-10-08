"""Execution attempt records for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from aic_control_centre.tasks.model import utc_now


EXECUTION_RECORDS_FILE_NAME = "executions.json"

EXECUTION_SOURCE_CLI = "cli"
EXECUTION_SOURCE_COORDINATOR = "coordinator"

KNOWN_EXECUTION_SOURCES = {
    EXECUTION_SOURCE_CLI,
    EXECUTION_SOURCE_COORDINATOR,
}

ENDED_AS_COMPLETED = "completed"
ENDED_AS_FAILED = "failed"
ENDED_AS_REQUEUED = "requeued"
ENDED_AS_ABANDONED = "abandoned"

# A caller may close an attempt with any of these. Only the registry
# marks an attempt abandoned, when it finds one left open.
CLOSING_ENDED_AS = {
    ENDED_AS_COMPLETED,
    ENDED_AS_FAILED,
    ENDED_AS_REQUEUED,
}

KNOWN_ENDED_AS = CLOSING_ENDED_AS | {ENDED_AS_ABANDONED}

ABANDONED_REASON = "attempt was still open when the task was started again"


@dataclass(frozen=True)
class ExecutionRecord:
    """Describe one attempt to run a task.

    An attempt is open until it ends. A closed record with no start time
    is written for a task that was already running before records
    existed, so that its ending is still recorded.
    """

    id: str
    task_id: str
    source: str
    target: str | None
    started_at: str | None
    ended_at: str | None
    ended_as: str | None
    reason: str

    def __post_init__(self) -> None:
        """Reject incomplete or inconsistent execution records."""
        if not self.id.strip():
            raise ValueError("execution record ID cannot be empty")

        if not self.task_id.strip():
            raise ValueError("task ID cannot be empty")

        if self.source not in KNOWN_EXECUTION_SOURCES:
            raise ValueError(f"unknown execution source: {self.source}")

        if self.ended_as is not None and self.ended_as not in KNOWN_ENDED_AS:
            raise ValueError(f"unknown execution end: {self.ended_as}")

        if (self.ended_at is None) != (self.ended_as is None):
            raise ValueError("ended_at and ended_as must be set together")

        if self.started_at is None and self.ended_as is None:
            raise ValueError("an open execution record needs a start time")

    @property
    def is_open(self) -> bool:
        """Return True while the attempt has not ended."""
        return self.ended_as is None

    @classmethod
    def begin(
        cls,
        task_id: str,
        source: str,
        target: str | None = None,
    ) -> ExecutionRecord:
        """Return a new open record that starts now."""
        return cls(
            id=str(uuid4()),
            task_id=task_id,
            source=source,
            target=target,
            started_at=utc_now(),
            ended_at=None,
            ended_as=None,
            reason="",
        )
