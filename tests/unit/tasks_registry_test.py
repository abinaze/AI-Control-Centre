"""Tests for the persistent task registry."""

import json

from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_READY,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry


def test_registry_starts_empty(tmp_path) -> None:
    """A new registry contains no tasks."""
    registry = TaskRegistry(tmp_path / "tasks.json")

    assert registry.list_tasks() == []


def test_registry_persists_task(tmp_path) -> None:
    """A task remains available after registry recreation."""
    registry_path = tmp_path / "tasks.json"
    registry = TaskRegistry(registry_path)

    task = Task.create(
        goal_id="goal-123",
        title="Audit authentication",
    )

    registry.add_task(task)

    new_registry = TaskRegistry(registry_path)
    tasks = new_registry.list_tasks()

    assert len(tasks) == 1
    assert tasks[0] == task


def test_registry_get_task_by_id(tmp_path) -> None:
    """A task can be retrieved by its ID."""
    registry = TaskRegistry(tmp_path / "tasks.json")

    task = Task.create(
        goal_id="goal-123",
        title="Audit authentication",
    )

    registry.add_task(task)

    assert registry.get_task(task.id) == task


def test_registry_returns_none_for_unknown_task(tmp_path) -> None:
    """Unknown task IDs return None."""
    registry = TaskRegistry(tmp_path / "tasks.json")

    assert registry.get_task("does-not-exist") is None


def test_registry_writes_json(tmp_path) -> None:
    """The registry persists readable JSON."""
    registry_path = tmp_path / "tasks.json"
    registry = TaskRegistry(registry_path)

    task = Task.create(
        goal_id="goal-123",
        title="Test JSON persistence",
    )

    registry.add_task(task)

    data = json.loads(registry_path.read_text(encoding="utf-8"))

    assert len(data) == 1
    assert data[0]["id"] == task.id
    assert data[0]["goal_id"] == task.goal_id
    assert data[0]["title"] == task.title
    assert data[0]["status"] == task.status


def test_registry_updates_task_status(tmp_path) -> None:
    """A valid task status transition is persisted."""
    registry_path = tmp_path / "tasks.json"
    registry = TaskRegistry(registry_path)

    task = Task.create(
        goal_id="goal-123",
        title="Run security audit",
    )

    registry.add_task(task)

    updated = registry.update_task_status(
        task.id,
        TASK_STATUS_READY,
    )

    assert updated.id == task.id
    assert updated.status == TASK_STATUS_READY
    assert updated.goal_id == task.goal_id
    assert updated.title == task.title
    assert updated.description == task.description
    assert updated.created_at == task.created_at
    assert updated.updated_at != task.updated_at

    new_registry = TaskRegistry(registry_path)

    assert new_registry.get_task(task.id) == updated


def test_registry_rejects_unknown_task_status_update(tmp_path) -> None:
    """Updating an unknown task raises a clear error."""
    registry = TaskRegistry(tmp_path / "tasks.json")

    try:
        registry.update_task_status("does-not-exist", TASK_STATUS_READY)
    except ValueError as exc:
        assert str(exc) == "Task not found: does-not-exist"
    else:
        raise AssertionError("Expected ValueError for unknown task")


def test_registry_rejects_invalid_status_transition(tmp_path) -> None:
    """Invalid task status transitions are rejected."""
    registry = TaskRegistry(tmp_path / "tasks.json")

    task = Task.create(
        goal_id="goal-123",
        title="Run security audit",
    )

    registry.add_task(task)

    try:
        registry.update_task_status(
            task.id,
            TASK_STATUS_COMPLETED,
        )
    except ValueError as exc:
        assert (
            str(exc)
            == "Invalid task status transition: pending -> completed"
        )
    else:
        raise AssertionError("Expected ValueError for invalid transition")
