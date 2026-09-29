"""Tests for goal CLI commands."""

from aic_control_centre.goals.commands import (
    create_goal,
    list_goals,
    show_goal_status,
)
from aic_control_centre.goals.model import (
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_IN_PROGRESS,
    Goal,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.model import TASK_STATUS_COMPLETED, Task
from aic_control_centre.tasks.registry import TaskRegistry


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


def test_show_goal_status_reconciles_tasks(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Showing a goal reconciles its status from persisted tasks."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    goal_registry = GoalRegistry(goal_path)
    task_registry = TaskRegistry(task_path)

    goal = Goal.create(
        description="Check goal status",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task_registry.add_task(
        Task.create(
            goal_id=goal.id,
            title="First task",
        )
    )

    monkeypatch.setattr(
        "aic_control_centre.goals.commands.GoalRegistry",
        lambda: GoalRegistry(goal_path),
    )
    monkeypatch.setattr(
        "aic_control_centre.goals.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    result = show_goal_status(goal.id)

    assert result == 0

    output = capsys.readouterr().out

    assert f"Goal: {goal.id}" in output
    assert "Project: TestProject" in output
    assert f"Status: {GOAL_STATUS_IN_PROGRESS}" in output
    assert "Description: Check goal status" in output

    assert GoalRegistry(goal_path).get_goal(goal.id).status == (
        GOAL_STATUS_IN_PROGRESS
    )


def test_show_goal_status_completed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Showing a goal reports completed when all tasks are completed."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    goal_registry = GoalRegistry(goal_path)
    task_registry = TaskRegistry(task_path)

    goal = Goal.create(
        description="Completed goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Completed task",
    )
    completed = Task(
        id=task.id,
        goal_id=task.goal_id,
        title=task.title,
        description=task.description,
        status=TASK_STATUS_COMPLETED,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
    task_registry.add_task(completed)

    monkeypatch.setattr(
        "aic_control_centre.goals.commands.GoalRegistry",
        lambda: GoalRegistry(goal_path),
    )
    monkeypatch.setattr(
        "aic_control_centre.goals.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    result = show_goal_status(goal.id)

    assert result == 0
    assert f"Status: {GOAL_STATUS_COMPLETED}" in capsys.readouterr().out


def test_show_goal_status_unknown_goal(tmp_path, monkeypatch, capsys) -> None:
    """Showing an unknown goal returns an error."""
    registry_path = tmp_path / "goals.json"

    monkeypatch.setattr(
        "aic_control_centre.goals.commands.GoalRegistry",
        lambda: GoalRegistry(registry_path),
    )

    result = show_goal_status("missing-goal")

    assert result == 1
    assert "Goal not found: missing-goal" in capsys.readouterr().out
