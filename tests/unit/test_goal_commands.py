"""Tests for goal CLI commands."""

from aic_control_centre.goals.commands import (
    create_goal,
    list_goals,
    show_goal_status,
)
from aic_control_centre.goals.registry import GoalRegistry


def test_create_goal_persists_goal(tmp_path, monkeypatch, capsys) -> None:
    """Creating a goal persists it and prints its ID."""
    registry_path = tmp_path / "goals.json"

    monkeypatch.setattr(
        "aic_control_centre.goals.commands.GoalRegistry",
        lambda: GoalRegistry(registry_path),
    )

    result = create_goal(
        description="Improve Aircursor security",
        project="Aircursor",
    )

    assert result == 0

    output = capsys.readouterr().out

    assert "Goal created." in output
    assert "Project: Aircursor" in output
    assert "Status: pending" in output
    assert "Description: Improve Aircursor security" in output

    goals = GoalRegistry(registry_path).list_goals()

    assert len(goals) == 1
    assert goals[0].description == "Improve Aircursor security"
    assert goals[0].project == "Aircursor"


def test_create_goal_rejects_empty_description(capsys) -> None:
    """Creating a goal rejects an empty description."""
    result = create_goal(
        description="   ",
        project="Aircursor",
    )

    assert result == 1
    assert "goal description cannot be empty" in capsys.readouterr().out


def test_create_goal_rejects_empty_project(capsys) -> None:
    """Creating a goal rejects an empty project."""
    result = create_goal(
        description="Build a feature",
        project="   ",
    )

    assert result == 1
    assert "project cannot be empty" in capsys.readouterr().out


def test_list_goals_prints_registered_goals(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Listing goals prints persisted goals."""
    registry_path = tmp_path / "goals.json"

    monkeypatch.setattr(
        "aic_control_centre.goals.commands.GoalRegistry",
        lambda: GoalRegistry(registry_path),
    )

    create_goal(
        description="First goal",
        project="ProjectA",
    )
    capsys.readouterr()

    create_goal(
        description="Second goal",
        project="ProjectB",
    )
    capsys.readouterr()

    result = list_goals()

    assert result == 0

    output = capsys.readouterr().out

    assert "Registered goals:" in output
    assert "Description: First goal" in output
    assert "Description: Second goal" in output


def test_list_goals_when_empty(capsys, tmp_path, monkeypatch) -> None:
    """Listing goals reports an empty registry."""
    registry_path = tmp_path / "goals.json"

    monkeypatch.setattr(
        "aic_control_centre.goals.commands.GoalRegistry",
        lambda: GoalRegistry(registry_path),
    )

    result = list_goals()

    assert result == 0
    assert "No goals registered." in capsys.readouterr().out


def test_show_goal_status(tmp_path, monkeypatch, capsys) -> None:
    """Showing a goal displays its status and details."""
    registry_path = tmp_path / "goals.json"
    registry = GoalRegistry(registry_path)

    from aic_control_centre.goals.model import Goal

    goal = Goal.create(
        description="Check goal status",
        project="TestProject",
    )
    registry.add_goal(goal)

    monkeypatch.setattr(
        "aic_control_centre.goals.commands.GoalRegistry",
        lambda: GoalRegistry(registry_path),
    )

    result = show_goal_status(goal.id)

    assert result == 0

    output = capsys.readouterr().out

    assert f"Goal: {goal.id}" in output
    assert "Project: TestProject" in output
    assert "Status: pending" in output
    assert "Description: Check goal status" in output


def test_show_goal_status_unknown_goal(tmp_path, monkeypatch, capsys) -> None:
    """Showing an unknown goal returns an error."""
    registry_path = tmp_path / "goals.json"

    monkeypatch.setattr(
        "aic_control_centre.goals.commands.GoalRegistry",
        lambda: GoalRegistry(registry_path),
    )

    result = show_goal_status("missing-goal")

    assert result == 1
    assert "goal not found: missing-goal" in capsys.readouterr().out
