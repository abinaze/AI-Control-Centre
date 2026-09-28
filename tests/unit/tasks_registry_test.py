"""Tests for the persistent task registry."""

import json

from aic_control_centre.tasks.model import Task
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
