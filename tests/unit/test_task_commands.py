"""Tests for task CLI commands."""

from dataclasses import replace

import pytest

from aic_control_centre.goals.model import (
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    GOAL_STATUS_IN_PROGRESS,
    Goal,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.commands import (
    complete_task,
    create_task,
    fail_task,
    list_tasks,
    mark_task_ready,
    show_task_status,
    start_task,
)
from aic_control_centre.tasks.model import Task
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


def test_create_task_reconciles_goal_status(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Creating a task moves its goal into progress."""
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

    assert create_task(goal.id, "Audit authentication") == 0
    capsys.readouterr()

    assert GoalRegistry(goal_path).get_goal(goal.id).status == (
        GOAL_STATUS_IN_PROGRESS
    )


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


def test_task_lifecycle_commands(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Lifecycle commands move a task through the valid states."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    goal_registry = GoalRegistry(goal_path)
    goal = Goal.create(
        description="Lifecycle goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    registry = TaskRegistry(task_path)
    task = Task.create(
        goal_id=goal.id,
        title="Lifecycle task",
    )
    registry.add_task(task)

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.GoalRegistry",
        lambda: GoalRegistry(goal_path),
    )
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    assert mark_task_ready(task.id) == 0
    capsys.readouterr()

    assert start_task(task.id) == 0
    capsys.readouterr()

    assert complete_task(task.id) == 0

    output = capsys.readouterr().out

    assert "Task status updated." in output
    assert "Status: completed" in output
    assert TaskRegistry(task_path).get_task(task.id).status == "completed"
    assert GoalRegistry(goal_path).get_goal(goal.id).status == (
        GOAL_STATUS_COMPLETED
    )


def test_task_fail_command(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The fail command moves a running task to failed."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    goal_registry = GoalRegistry(goal_path)
    goal = Goal.create(
        description="Failing goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    registry = TaskRegistry(task_path)
    task = Task.create(
        goal_id=goal.id,
        title="Failing task",
    )
    registry.add_task(task)

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.GoalRegistry",
        lambda: GoalRegistry(goal_path),
    )
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    assert mark_task_ready(task.id) == 0
    capsys.readouterr()

    assert start_task(task.id) == 0
    capsys.readouterr()

    assert fail_task(task.id) == 0

    output = capsys.readouterr().out

    assert "Status: failed" in output
    assert TaskRegistry(task_path).get_task(task.id).status == "failed"
    assert GoalRegistry(goal_path).get_goal(goal.id).status == GOAL_STATUS_FAILED


def test_multiple_tasks_keep_goal_in_progress_until_all_complete(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A goal remains in progress until every task is completed."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    goal_registry = GoalRegistry(goal_path)
    goal = Goal.create(
        description="Multiple tasks",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    registry = TaskRegistry(task_path)

    first = Task.create(
        goal_id=goal.id,
        title="First task",
    )
    second = Task.create(
        goal_id=goal.id,
        title="Second task",
    )
    registry.add_task(first)
    registry.add_task(second)

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.GoalRegistry",
        lambda: GoalRegistry(goal_path),
    )
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    assert mark_task_ready(first.id) == 0
    capsys.readouterr()

    assert start_task(first.id) == 0
    capsys.readouterr()

    assert complete_task(first.id) == 0
    capsys.readouterr()

    assert GoalRegistry(goal_path).get_goal(goal.id).status == (
        GOAL_STATUS_IN_PROGRESS
    )

    assert mark_task_ready(second.id) == 0
    capsys.readouterr()

    assert start_task(second.id) == 0
    capsys.readouterr()

    assert complete_task(second.id) == 0
    capsys.readouterr()

    assert GoalRegistry(goal_path).get_goal(goal.id).status == (
        GOAL_STATUS_COMPLETED
    )


def test_task_lifecycle_command_rejects_invalid_transition(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Lifecycle commands report invalid transitions."""
    task_path = tmp_path / "tasks.json"
    registry = TaskRegistry(task_path)

    task = Task.create(
        goal_id="goal-123",
        title="Invalid transition task",
    )
    registry.add_task(task)

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    result = complete_task(task.id)

    assert result == 1

    output = capsys.readouterr().out

    assert "Invalid task status transition: pending -> completed" in output
    assert TaskRegistry(task_path).get_task(task.id).status == "pending"


def test_task_lifecycle_command_rejects_unknown_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Lifecycle commands report unknown task IDs."""
    task_path = tmp_path / "tasks.json"

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    result = mark_task_ready("missing-task")

    assert result == 1
    assert "Task not found: missing-task" in capsys.readouterr().out


def test_task_lifecycle_command_rejects_empty_task_id(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Lifecycle commands reject empty task IDs."""
    task_path = tmp_path / "tasks.json"

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )

    result = start_task("   ")

    assert result == 1
    assert "task ID cannot be empty" in capsys.readouterr().out


def test_create_task_rejects_completed_goal(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Creating a task for a completed goal is rejected."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    goal_registry = GoalRegistry(goal_path)

    goal = Goal.create(
        description="Completed goal",
        project="TestProject",
    )
    completed_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status=GOAL_STATUS_COMPLETED,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )
    goal_registry.add_goal(completed_goal)

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
        title="Should not be created",
    )

    assert result == 1
    assert (
        f"Cannot create task for completed goal: {goal.id}"
        in capsys.readouterr().out
    )
    assert TaskRegistry(task_path).list_tasks() == []


def test_create_task_rejects_failed_goal(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Creating a task for a failed goal is rejected."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"

    goal_registry = GoalRegistry(goal_path)

    goal = Goal.create(
        description="Failed goal",
        project="TestProject",
    )
    failed_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status=GOAL_STATUS_FAILED,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )
    goal_registry.add_goal(failed_goal)

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
        title="Should not be created",
    )

    assert result == 1
    assert (
        f"Cannot create task for failed goal: {goal.id}"
        in capsys.readouterr().out
    )
    assert TaskRegistry(task_path).list_tasks() == []


def _patch_registries(monkeypatch, goal_path, task_path) -> None:
    """Point the task commands at temporary registries."""
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.GoalRegistry",
        lambda: GoalRegistry(goal_path),
    )
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: TaskRegistry(task_path),
    )


def _add_goal(goal_path, status) -> Goal:
    """Persist a goal with an explicit status."""
    goal = replace(
        Goal.create(description="Gate goal", project="TestProject"),
        status=status,
    )
    GoalRegistry(goal_path).add_goal(goal)
    return goal


def _add_task(task_path, goal_id, status="pending") -> Task:
    """Persist a task, moving it to ready when requested."""
    registry = TaskRegistry(task_path)
    task = Task.create(goal_id=goal_id, title="Gate task")
    registry.add_task(task)

    if status == "ready":
        registry.update_task_status(task.id, "ready")

    return task


@pytest.mark.parametrize(
    ("goal_status", "reason"),
    [
        (GOAL_STATUS_FAILED, "parent goal is failed"),
        (GOAL_STATUS_COMPLETED, "parent goal is completed"),
    ],
)
def test_start_task_rejects_task_in_closed_goal(
    tmp_path,
    monkeypatch,
    capsys,
    goal_status,
    reason,
) -> None:
    """A ready task cannot start while its parent goal is closed."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"
    goal = _add_goal(goal_path, goal_status)
    task = _add_task(task_path, goal.id, status="ready")
    _patch_registries(monkeypatch, goal_path, task_path)

    assert start_task(task.id) == 1

    assert (
        f"Error: task is not ready for execution: {reason}"
        in capsys.readouterr().out
    )
    assert TaskRegistry(task_path).get_task(task.id).status == "ready"


def test_start_task_rejects_task_with_missing_goal(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A task without a parent goal cannot start."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"
    task = _add_task(task_path, "missing-goal", status="ready")
    _patch_registries(monkeypatch, goal_path, task_path)

    assert start_task(task.id) == 1

    assert "parent goal not found" in capsys.readouterr().out
    assert TaskRegistry(task_path).get_task(task.id).status == "ready"


def test_start_task_rejects_pending_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A task that is not ready cannot start."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"
    goal = _add_goal(goal_path, GOAL_STATUS_IN_PROGRESS)
    task = _add_task(task_path, goal.id)
    _patch_registries(monkeypatch, goal_path, task_path)

    assert start_task(task.id) == 1

    assert "task status is pending" in capsys.readouterr().out
    assert TaskRegistry(task_path).get_task(task.id).status == "pending"


def test_start_task_still_reports_unknown_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Unknown task IDs keep the lifecycle transition's error message."""
    _patch_registries(
        monkeypatch,
        tmp_path / "goals.json",
        tmp_path / "tasks.json",
    )

    assert start_task("missing-task") == 1

    assert "Task not found: missing-task" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("goal_status", "reason"),
    [
        (GOAL_STATUS_FAILED, "parent goal is failed"),
        (GOAL_STATUS_COMPLETED, "parent goal is completed"),
    ],
)
def test_mark_task_ready_rejects_task_in_closed_goal(
    tmp_path,
    monkeypatch,
    capsys,
    goal_status,
    reason,
) -> None:
    """A pending task cannot become ready while its goal is closed."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"
    goal = _add_goal(goal_path, goal_status)
    task = _add_task(task_path, goal.id)
    _patch_registries(monkeypatch, goal_path, task_path)

    assert mark_task_ready(task.id) == 1

    assert (
        f"Error: task cannot be marked ready: {reason}"
        in capsys.readouterr().out
    )
    assert TaskRegistry(task_path).get_task(task.id).status == "pending"


def test_mark_task_ready_rejects_task_with_missing_goal(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A task without a parent goal cannot become ready."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"
    task = _add_task(task_path, "missing-goal")
    _patch_registries(monkeypatch, goal_path, task_path)

    assert mark_task_ready(task.id) == 1

    assert "parent goal not found" in capsys.readouterr().out
    assert TaskRegistry(task_path).get_task(task.id).status == "pending"


def test_mark_task_ready_allows_task_in_open_goal(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A pending task in an open goal can still become ready."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"
    goal = _add_goal(goal_path, GOAL_STATUS_IN_PROGRESS)
    task = _add_task(task_path, goal.id)
    _patch_registries(monkeypatch, goal_path, task_path)

    assert mark_task_ready(task.id) == 0

    assert "Status: ready" in capsys.readouterr().out
    assert TaskRegistry(task_path).get_task(task.id).status == "ready"


def test_failed_goal_blocks_remaining_tasks_from_cli_lifecycle(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Once a goal has failed, its other tasks cannot be ready or started."""
    goal_path = tmp_path / "goals.json"
    task_path = tmp_path / "tasks.json"
    goal = _add_goal(goal_path, GOAL_STATUS_IN_PROGRESS)
    first = _add_task(task_path, goal.id)
    second = _add_task(task_path, goal.id)
    _patch_registries(monkeypatch, goal_path, task_path)

    assert mark_task_ready(first.id) == 0
    assert start_task(first.id) == 0
    assert fail_task(first.id) == 0
    assert GoalRegistry(goal_path).get_goal(goal.id).status == (
        GOAL_STATUS_FAILED
    )
    capsys.readouterr()

    assert mark_task_ready(second.id) == 1
    assert "parent goal is failed" in capsys.readouterr().out
    assert TaskRegistry(task_path).get_task(second.id).status == "pending"

    TaskRegistry(task_path).update_task_status(second.id, "ready")

    assert start_task(second.id) == 1
    assert "parent goal is failed" in capsys.readouterr().out
    assert TaskRegistry(task_path).get_task(second.id).status == "ready"
