"""Tests for the persistent task registry."""

import json

import pytest

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
    tasks = data["tasks"]

    assert data["schema_version"] == 1
    assert len(tasks) == 1
    assert tasks[0]["id"] == task.id
    assert tasks[0]["goal_id"] == task.goal_id
    assert tasks[0]["title"] == task.title
    assert tasks[0]["status"] == task.status


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


def test_registry_lists_tasks_for_goal(tmp_path) -> None:
    """The registry returns only tasks belonging to the requested goal."""
    registry = TaskRegistry(tmp_path / "tasks.json")

    first = Task.create(
        goal_id="goal-123",
        title="First task",
    )
    second = Task.create(
        goal_id="goal-456",
        title="Second task",
    )
    third = Task.create(
        goal_id="goal-123",
        title="Third task",
    )

    registry.add_task(first)
    registry.add_task(second)
    registry.add_task(third)

    assert registry.list_tasks_for_goal("goal-123") == [first, third]
    assert registry.list_tasks_for_goal("goal-456") == [second]
    assert registry.list_tasks_for_goal("missing-goal") == []


def _fail_replace(*args, **kwargs) -> None:
    """Simulate a crash while a state file is being replaced."""
    raise OSError("simulated crash")


def test_registry_failed_save_keeps_existing_file(
    tmp_path,
    monkeypatch,
) -> None:
    """A failed write leaves the previous registry file intact."""
    registry_path = tmp_path / "tasks.json"
    registry = TaskRegistry(registry_path)
    first = Task.create(goal_id="goal-123", title="First task")
    registry.add_task(first)
    before = registry_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        "aic_control_centre.storage.os.replace",
        _fail_replace,
    )

    with pytest.raises(OSError, match="simulated crash"):
        registry.add_task(Task.create(goal_id="goal-123", title="Second"))

    assert registry_path.read_text(encoding="utf-8") == before
    assert TaskRegistry(registry_path).list_tasks() == [first]
    assert [path.name for path in tmp_path.iterdir()] == ["tasks.json"]


def test_registry_failed_status_update_keeps_existing_status(
    tmp_path,
    monkeypatch,
) -> None:
    """A failed status write leaves the stored status unchanged."""
    registry_path = tmp_path / "tasks.json"
    registry = TaskRegistry(registry_path)
    task = Task.create(goal_id="goal-123", title="Status task")
    registry.add_task(task)
    before = registry_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        "aic_control_centre.storage.os.replace",
        _fail_replace,
    )

    with pytest.raises(OSError, match="simulated crash"):
        registry.update_task_status(task.id, TASK_STATUS_READY)

    assert registry_path.read_text(encoding="utf-8") == before
    assert TaskRegistry(registry_path).get_task(task.id).status == "pending"
