"""Tests for the persistent goal registry."""

import json

from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry


def test_registry_starts_empty(tmp_path) -> None:
    """A new registry contains no goals."""
    registry = GoalRegistry(tmp_path / "goals.json")

    assert registry.list_goals() == []


def test_registry_persists_goal(tmp_path) -> None:
    """A goal remains available after registry recreation."""
    registry_path = tmp_path / "goals.json"
    registry = GoalRegistry(registry_path)

    goal = Goal.create(
        description="Improve the security of Aircursor",
        project="Aircursor",
    )

    registry.add_goal(goal)

    new_registry = GoalRegistry(registry_path)
    goals = new_registry.list_goals()

    assert len(goals) == 1
    assert goals[0] == goal


def test_registry_get_goal_by_id(tmp_path) -> None:
    """A goal can be retrieved by its ID."""
    registry = GoalRegistry(tmp_path / "goals.json")

    goal = Goal.create(
        description="Build a test goal",
        project="TestProject",
    )

    registry.add_goal(goal)

    assert registry.get_goal(goal.id) == goal


def test_registry_returns_none_for_unknown_goal(tmp_path) -> None:
    """Unknown goal IDs return None."""
    registry = GoalRegistry(tmp_path / "goals.json")

    assert registry.get_goal("does-not-exist") is None


def test_registry_writes_json(tmp_path) -> None:
    """The registry persists readable JSON."""
    registry_path = tmp_path / "goals.json"
    registry = GoalRegistry(registry_path)

    goal = Goal.create(
        description="Test JSON persistence",
        project="TestProject",
    )

    registry.add_goal(goal)

    data = json.loads(registry_path.read_text(encoding="utf-8"))

    assert len(data) == 1
    assert data[0]["id"] == goal.id
    assert data[0]["description"] == goal.description
    assert data[0]["project"] == goal.project
    assert data[0]["status"] == goal.status


def test_registry_updates_goal(tmp_path) -> None:
    """A goal update is persisted by its ID."""
    registry_path = tmp_path / "goals.json"
    registry = GoalRegistry(registry_path)

    goal = Goal.create(
        description="Original goal",
        project="TestProject",
    )
    registry.add_goal(goal)

    updated = Goal(
        id=goal.id,
        description="Updated goal",
        project=goal.project,
        status="in_progress",
        created_at=goal.created_at,
        updated_at="2026-01-01T00:00:00+00:00",
    )

    result = registry.update_goal(updated)

    assert result == updated
    assert GoalRegistry(registry_path).get_goal(goal.id) == updated


def test_registry_rejects_unknown_goal_update(tmp_path) -> None:
    """Updating an unknown goal raises a clear error."""
    registry = GoalRegistry(tmp_path / "goals.json")

    goal = Goal.create(
        description="Unknown goal",
        project="TestProject",
    )

    try:
        registry.update_goal(goal)
    except ValueError as exc:
        assert str(exc) == f"Goal not found: {goal.id}"
    else:
        raise AssertionError("Expected ValueError for unknown goal")
