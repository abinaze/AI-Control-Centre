"""Task data model for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4


TASK_STATUS_PENDING = "pending"


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
