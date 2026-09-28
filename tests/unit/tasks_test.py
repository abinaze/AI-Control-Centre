"""Tests for the Task data model."""

from datetime import datetime
from uuid import UUID

from aic_control_centre.tasks.model import (
    TASK_STATUS_PENDING,
    Task,
)


def test_task_create_generates_pending_task() -> None:
    """Creating a task generates the expected initial state."""
    task = Task.create(
        goal_id="goal-123",
        title="Audit Aircursor authentication",
    )

    UUID(task.id)

    assert task.goal_id == "goal-123"
    assert task.title == "Audit Aircursor authentication"
    assert task.description == ""
    assert task.status == TASK_STATUS_PENDING
    assert task.created_at == task.updated_at


def test_task_create_generates_utc_timestamps() -> None:
    """Created tasks contain valid UTC timestamps."""
    task = Task.create(
        goal_id="goal-123",
        title="Test task",
    )

    created = datetime.fromisoformat(task.created_at)
    updated = datetime.fromisoformat(task.updated_at)

    assert created.tzinfo is not None
    assert updated.tzinfo is not None
    assert created.utcoffset().total_seconds() == 0
    assert updated.utcoffset().total_seconds() == 0


def test_task_ids_are_unique() -> None:
    """Separate tasks receive different IDs."""
    first = Task.create(
        goal_id="goal-123",
        title="First task",
    )
    second = Task.create(
        goal_id="goal-123",
        title="Second task",
    )

    assert first.id != second.id
