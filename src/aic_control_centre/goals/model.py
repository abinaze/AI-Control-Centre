"""Goal data model for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4


GOAL_STATUS_PENDING = "pending"
GOAL_STATUS_IN_PROGRESS = "in_progress"
GOAL_STATUS_COMPLETED = "completed"
GOAL_STATUS_FAILED = "failed"

KNOWN_GOAL_STATUSES = {
    GOAL_STATUS_PENDING,
    GOAL_STATUS_IN_PROGRESS,
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
}


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Goal:
    """A persistent high-level goal."""

    id: str
    description: str
    project: str
    status: str
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        description: str,
        project: str,
    ) -> "Goal":
        """Create a new pending goal."""
        timestamp = utc_now()

        return cls(
            id=str(uuid4()),
            description=description,
            project=project,
            status=GOAL_STATUS_PENDING,
            created_at=timestamp,
            updated_at=timestamp,
        )
