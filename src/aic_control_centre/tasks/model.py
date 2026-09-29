"""Task data model for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4


TASK_STATUS_PENDING = "pending"
TASK_STATUS_READY = "ready"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"


TASK_STATUS_TRANSITIONS = {
    TASK_STATUS_PENDING: {TASK_STATUS_READY},
    TASK_STATUS_READY: {TASK_STATUS_RUNNING},
    TASK_STATUS_RUNNING: {
        TASK_STATUS_COMPLETED,
        TASK_STATUS_FAILED,
    },
    TASK_STATUS_COMPLETED: set(),
    TASK_STATUS_FAILED: set(),
}


def can_transition(current_status: str, new_status: str) -> bool:
    """Return whether a task can move to the requested status."""
    return new_status in TASK_STATUS_TRANSITIONS.get(current_status, set())


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Task:
    """A persistent task belonging to a goal."""

    id: str
    goal_id: str
    title: str
    description: str
    status: str
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        goal_id: str,
        title: str,
        description: str = "",
    ) -> "Task":
        """Create a new pending task."""
        timestamp = utc_now()

        return cls(
            id=str(uuid4()),
            goal_id=goal_id,
            title=title,
            description=description,
            status=TASK_STATUS_PENDING,
            created_at=timestamp,
            updated_at=timestamp,
        )
