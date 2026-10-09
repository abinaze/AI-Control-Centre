"""Tests for the Goal data model."""

from datetime import datetime
from uuid import UUID

import aic_control_centre.goals.model as goal_model
import aic_control_centre.readiness.tasks as readiness_tasks
import aic_control_centre.validation.goal_tasks as validation_tasks
from aic_control_centre.goals.model import (
    GOAL_STATUS_PENDING,
    KNOWN_GOAL_STATUSES,
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


def test_known_goal_statuses_match_the_goal_status_constants() -> None:
    """Every GOAL_STATUS_ constant is a known status, and the reverse."""
    declared = {
        value
        for name, value in vars(goal_model).items()
        if name.startswith("GOAL_STATUS_")
    }

    assert KNOWN_GOAL_STATUSES == declared
    assert len(KNOWN_GOAL_STATUSES) == 4


def test_new_goals_start_with_a_known_status() -> None:
    """A newly created goal has a status the tool recognises."""
    goal = Goal.create(description="Known status", project="TestProject")

    assert goal.status in KNOWN_GOAL_STATUSES


def test_readiness_and_validation_use_the_shared_goal_statuses() -> None:
    """Neither module keeps its own copy that could drift."""
    assert readiness_tasks.KNOWN_GOAL_STATUSES is KNOWN_GOAL_STATUSES
    assert validation_tasks.KNOWN_GOAL_STATUSES is KNOWN_GOAL_STATUSES
