"""Tests for aic goal archived with a goal id."""

import sys

from aic_control_centre.cli import main
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _project(monkeypatch, tmp_path, name="app"):
    directory = tmp_path / "work" / name
    directory.mkdir(parents=True)
    added = run_cli(monkeypatch, tmp_path, "project", "add", str(directory))

    assert added == 0

    return directory


def _ran_goal(monkeypatch, tmp_path, capsys):
    """Run a task for real with noop, and return the goal, task and history."""
    goal = Goal.create("Ship it", "app")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal.id, "first")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    assert run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "noop",
    ) == 0

    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "task", "history", task.id) == 0

    return goal, task, capsys.readouterr().out


def _archive(monkeypatch, tmp_path, goal):
    code = run_cli(
        monkeypatch,
        tmp_path,
        "goal",
        "archive",
        goal.id,
        "--reason",
        "all shipped",
    )

    assert code == 0


def _state(tmp_path):
    return {path.name: path.read_bytes() for path in tmp_path.glob("*.json")}


def test_the_attempts_read_as_task_history_printed_them(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The text of the attempts is the same, time stamps and all."""
    _project(monkeypatch, tmp_path)
    goal, task, history = _ran_goal(monkeypatch, tmp_path, capsys)
    attempts = history.split("Attempts: 1\n", 1)[1]
    _archive(monkeypatch, tmp_path, goal)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "goal", "archived", goal.id) == 0

    output = capsys.readouterr().out

    assert attempts.startswith("\nAttempt 1\n")
    assert attempts in output
    assert f"Archived goal: {goal.id}" in output
    assert f"Task: {task.id}\nStatus: completed\nTitle: first\n" in output
    assert "Reason: all shipped" in output


def test_spaces_around_the_goal_id_are_ignored(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The id is trimmed, as the other commands trim what they are given."""
    _project(monkeypatch, tmp_path)
    goal, _, _ = _ran_goal(monkeypatch, tmp_path, capsys)
    _archive(monkeypatch, tmp_path, goal)
    capsys.readouterr()

    assert run_cli(
        monkeypatch,
        tmp_path,
        "goal",
        "archived",
        f"  {goal.id}  ",
    ) == 0
    assert f"Archived goal: {goal.id}" in capsys.readouterr().out


def test_a_goal_that_is_not_known_is_refused(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The error names the id, and nothing is written."""
    _project(monkeypatch, tmp_path)
    before = _state(tmp_path)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "goal", "archived", "nope") == 1

    assert capsys.readouterr().out == "Error: goal nope is not archived\n"
    assert _state(tmp_path) == before
    assert not (tmp_path / "archive.json").exists()


def test_a_goal_that_is_still_active_is_refused_and_says_so(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """It is not in the archive, and the message tells why."""
    _project(monkeypatch, tmp_path)
    goal = Goal.create("Still going", "app")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "goal", "archived", goal.id) == 1

    assert capsys.readouterr().out == (
        f"Error: goal {goal.id} is not archived; it is still active\n"
    )


def test_showing_an_archived_goal_changes_no_file(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Every state file is the same bytes afterwards."""
    _project(monkeypatch, tmp_path)
    goal, _, _ = _ran_goal(monkeypatch, tmp_path, capsys)
    _archive(monkeypatch, tmp_path, goal)
    before = _state(tmp_path)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "goal", "archived", goal.id) == 0
    assert _state(tmp_path) == before


def test_an_archive_that_cannot_be_read_is_an_error_and_is_kept(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """It is not shown as empty, and it is not changed."""
    path = tmp_path / "archive.json"
    path.write_bytes(b"{ not json")

    assert run_cli(monkeypatch, tmp_path, "goal", "archived", "any") == 1

    assert "is not valid JSON" in capsys.readouterr().out
    assert path.read_bytes() == b"{ not json"


def test_without_an_id_the_command_still_lists_the_archive(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The listing is what it was."""
    _project(monkeypatch, tmp_path)
    goal, _, _ = _ran_goal(monkeypatch, tmp_path, capsys)
    _archive(monkeypatch, tmp_path, goal)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "goal", "archived") == 0

    output = capsys.readouterr().out

    assert "Archived goals:" in output
    assert f"- {goal.id}" in output
    assert "Task: " not in output
