"""Tests for task CLI commands."""

from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.commands import (
    create_task,
    list_tasks,
    show_task_status,
)
from aic_control_centre.tasks.registry import TaskRegistry


def test_create_task_persists_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Creating a task persists it and prints its ID."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    goal_registry = GoalRegistry(goal_path)
    goal = Goal.create(
        description="Improve Aircursor security",
        project="Aircursor",
    )
    goal_registry.add_goal(goal)

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.GoalRegistry",
        lambda: GoalRegistry(goal_path),
    )
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    result = create_task(
        goal_id=goal.id,
        title="Audit authentication",
    )

    assert result == 0

    output = capsys.readouterr().out

    assert "Task created." in output
    assert f"Goal: {goal.id}" in output
    assert "Status: pending" in output
    assert "Title: Audit authentication" in output

    tasks = TaskRegistry(task_path).list_tasks()

    assert len(tasks) == 1
    assert tasks[0].goal_id == goal.id
    assert tasks[0].title == "Audit authentication"


def test_create_task_rejects_unknown_goal(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Creating a task rejects an unknown goal."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.GoalRegistry",
        lambda: GoalRegistry(goal_path),
    )
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    result = create_task(
        goal_id="missing-goal",
        title="Audit authentication",
    )

    assert result == 1
    assert "goal not found: missing-goal" in capsys.readouterr().out


def test_create_task_rejects_empty_title(capsys) -> None:
    """Creating a task rejects an empty title."""
    result = create_task(
        goal_id="goal-123",
        title="   ",
    )

    assert result == 1
    assert "task title cannot be empty" in capsys.readouterr().out


def test_list_tasks_prints_registered_tasks(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Listing tasks prints persisted tasks."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    goal_registry = GoalRegistry(goal_path)
    goal = Goal.create(
        description="Test goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.GoalRegistry",
        lambda: GoalRegistry(goal_path),
    )
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    create_task(goal.id, "First task")
    capsys.readouterr()

    create_task(goal.id, "Second task")
    capsys.readouterr()

    result = list_tasks()

    assert result == 0

    output = capsys.readouterr().out

    assert "Registered tasks:" in output
    assert "Title: First task" in output
    assert "Title: Second task" in output


def test_list_tasks_when_empty(capsys, tmp_path, monkeypatch) -> None:
    """Listing tasks reports an empty registry."""
    task_path = tmp_path / "tasks.json"

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    result = list_tasks()

    assert result == 0
    assert "No tasks registered." in capsys.readouterr().out


def test_show_task_status(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Showing a task displays its status and details."""
    task_path = tmp_path / "tasks.json"
    registry = TaskRegistry(task_path)

    from aic_control_centre.tasks.model import Task

    task = Task.create(
        goal_id="goal-123",
        title="Check task status",
    )
    registry.add_task(task)

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    result = show_task_status(task.id)

    assert result == 0

    output = capsys.readouterr().out

    assert f"Task: {task.id}" in output
    assert "Goal: goal-123" in output
    assert "Status: pending" in output
    assert "Title: Check task status" in output


def test_show_task_status_unknown_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Showing an unknown task returns an error."""
    task_path = tmp_path / "tasks.json"

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    result = show_task_status("missing-task")

    assert result == 1
    assert "task not found: missing-task" in capsys.readouterr().out
