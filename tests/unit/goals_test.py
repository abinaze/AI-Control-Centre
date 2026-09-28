"""Tests for the Goal data model."""

from datetime import datetime
from uuid import UUID

from aic_control_centre.goals.model import (
    GOAL_STATUS_PENDING,
    Goal,
)


def test_goal_create_generates_pending_goal() -> None:
    """Creating a goal generates the expected initial state."""
    goal = Goal.create(
        description="Improve the security of Aircursor",
        project="Aircursor",
    )

    UUID(goal.id)

    assert goal.description == "Improve the security of Aircursor"
    assert goal.project == "Aircursor"
    assert goal.status == GOAL_STATUS_PENDING
    assert goal.created_at == goal.updated_at


def test_goal_create_generates_utc_timestamps() -> None:
    """Created goals contain valid UTC timestamps."""
    goal = Goal.create(
        description="Build a test goal",
        project="TestProject",
    )

    created = datetime.fromisoformat(goal.created_at)
    updated = datetime.fromisoformat(goal.updated_at)

    assert created.tzinfo is not None
    assert updated.tzinfo is not None
    assert created.utcoffset().total_seconds() == 0
    assert updated.utcoffset().total_seconds() == 0


def test_goal_ids_are_unique() -> None:
    """Separate goals receive different IDs."""
    first = Goal.create(
        description="First goal",
        project="Project",
    )
    second = Goal.create(
        description="Second goal",
        project="Project",
    )

    assert first.id != second.id
