"""Tests for the persistent goal registry."""

import json

import pytest

from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.storage import UnsupportedSchemaVersionError


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
    goals = data["goals"]

    assert data["schema_version"] == 1
    assert len(goals) == 1
    assert goals[0]["id"] == goal.id
    assert goals[0]["description"] == goal.description
    assert goals[0]["project"] == goal.project
    assert goals[0]["status"] == goal.status


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


def _fail_replace(*args, **kwargs) -> None:
    """Simulate a crash while a state file is being replaced."""
    raise OSError("simulated crash")


def test_registry_failed_save_keeps_existing_file(
    tmp_path,
    monkeypatch,
) -> None:
    """A failed write leaves the previous registry file intact."""
    registry_path = tmp_path / "goals.json"
    registry = GoalRegistry(registry_path)
    first = Goal.create(description="First goal", project="TestProject")
    registry.add_goal(first)
    before = registry_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        "aic_control_centre.storage.os.replace",
        _fail_replace,
    )

    with pytest.raises(OSError, match="simulated crash"):
        registry.add_goal(
            Goal.create(description="Second goal", project="TestProject"),
        )

    assert registry_path.read_text(encoding="utf-8") == before
    assert GoalRegistry(registry_path).list_goals() == [first]
    assert [path.name for path in tmp_path.iterdir()] == ["goals.json"]


def _make_legacy(registry_path, collection) -> None:
    """Rewrite a versioned state file as a pre-versioning bare list."""
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    registry_path.write_text(
        json.dumps(data[collection], indent=2),
        encoding="utf-8",
    )


def test_registry_reads_legacy_list_file_without_rewriting_it(
    tmp_path,
) -> None:
    """A pre-versioning bare list is read and left untouched."""
    registry_path = tmp_path / "goals.json"
    goal = Goal.create(description="Legacy goal", project="TestProject")
    GoalRegistry(registry_path).add_goal(goal)
    _make_legacy(registry_path, "goals")
    before = registry_path.read_bytes()

    assert GoalRegistry(registry_path).list_goals() == [goal]
    assert registry_path.read_bytes() == before


def test_registry_upgrades_legacy_file_on_save(tmp_path) -> None:
    """Saving a legacy file rewrites it in the versioned shape."""
    registry_path = tmp_path / "goals.json"
    registry = GoalRegistry(registry_path)
    first = Goal.create(description="First goal", project="TestProject")
    second = Goal.create(description="Second goal", project="TestProject")
    registry.add_goal(first)
    _make_legacy(registry_path, "goals")

    registry.add_goal(second)

    data = json.loads(registry_path.read_text(encoding="utf-8"))

    assert data["schema_version"] == 1
    assert [item["id"] for item in data["goals"]] == [first.id, second.id]


def test_registry_refuses_newer_schema_version(tmp_path) -> None:
    """A file from a newer schema version is refused and left untouched."""
    registry_path = tmp_path / "goals.json"
    text = json.dumps({"schema_version": 99, "goals": []})
    registry_path.write_text(text, encoding="utf-8")
    registry = GoalRegistry(registry_path)

    with pytest.raises(UnsupportedSchemaVersionError):
        registry.list_goals()

    with pytest.raises(UnsupportedSchemaVersionError):
        registry.add_goal(
            Goal.create(description="New goal", project="TestProject"),
        )

    assert registry_path.read_text(encoding="utf-8") == text
