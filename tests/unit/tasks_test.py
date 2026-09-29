"""Tests for the Task data model."""

from datetime import datetime
from uuid import UUID

from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    TASK_STATUS_READY,
    TASK_STATUS_RUNNING,
    Task,
    can_transition,
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

def test_valid_task_status_transitions() -> None:
    """Valid task lifecycle transitions are accepted."""
    valid_transitions = [
        (TASK_STATUS_PENDING, TASK_STATUS_READY),
        (TASK_STATUS_READY, TASK_STATUS_RUNNING),
        (TASK_STATUS_RUNNING, TASK_STATUS_COMPLETED),
        (TASK_STATUS_RUNNING, TASK_STATUS_FAILED),
    ]

    for current_status, new_status in valid_transitions:
        assert can_transition(current_status, new_status)


def test_invalid_task_status_transitions() -> None:
    """Invalid task lifecycle transitions are rejected."""
    invalid_transitions = [
        (TASK_STATUS_PENDING, TASK_STATUS_RUNNING),
        (TASK_STATUS_PENDING, TASK_STATUS_COMPLETED),
        (TASK_STATUS_READY, TASK_STATUS_COMPLETED),
        (TASK_STATUS_RUNNING, TASK_STATUS_PENDING),
        (TASK_STATUS_COMPLETED, TASK_STATUS_RUNNING),
        (TASK_STATUS_FAILED, TASK_STATUS_RUNNING),
    ]

    for current_status, new_status in invalid_transitions:
        assert not can_transition(current_status, new_status)


def test_unknown_task_status_transitions_are_rejected() -> None:
    """Unknown task statuses cannot participate in transitions."""
    assert not can_transition("unknown", TASK_STATUS_READY)
    assert not can_transition(TASK_STATUS_PENDING, "unknown")
    assert not can_transition("unknown", "unknown")

