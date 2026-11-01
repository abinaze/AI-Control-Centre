"""Tests for aic goal archive."""

import sys
from dataclasses import replace

import pytest

from aic_control_centre.cli import main
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.goals.archive import GoalArchive
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


def _goal(tmp_path, statuses=("completed", "failed"), project="app"):
    """Add a goal with one task for each status, and a record for each."""
    goal = Goal.create("Ship it", project)
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    tasks = TaskRegistry(tmp_path / "tasks.json")
    records = ExecutionRecordRegistry.beside(tasks.registry_path)
    added = []

    for number, status in enumerate(statuses):
        task = replace(Task.create(goal.id, f"task {number}"), status=status)
        tasks.add_task(task)
        added.append(task)

        if status in ("completed", "failed"):
            records.open_attempt(task.id, "coordinator", "noop")
            records.close_attempt(task.id, status, "why", "coordinator")

    return goal, added


def _archive(tmp_path):
    return GoalArchive.beside(tmp_path / "tasks.json")


def _archive_goal(monkeypatch, tmp_path, goal, reason="tidy up"):
    return run_cli(
        monkeypatch,
        tmp_path,
        "goal",
        "archive",
        goal.id,
        "--reason",
        reason,
    )


def test_a_finished_goal_is_archived(tmp_path, monkeypatch, capsys) -> None:
    """The output says what moved, and nothing is deleted."""
    directory = _project(monkeypatch, tmp_path)
    goal, _ = _goal(tmp_path)
    capsys.readouterr()

    assert _archive_goal(monkeypatch, tmp_path, goal) == 0

    output = capsys.readouterr().out

    assert f"Goal archived: {goal.id}" in output
    assert "Project: app" in output
    assert f"Project directory: {directory.resolve()}" in output
    assert "Tasks archived: 2" in output
    assert "Execution records archived: 2" in output
    assert "Reason: tidy up" in output
    assert f"Archive: {tmp_path / 'archive.json'}" in output
    assert "Nothing was deleted." in output

    assert run_cli(monkeypatch, tmp_path, "goal", "list") == 0
    assert "No goals registered." in capsys.readouterr().out
    assert run_cli(monkeypatch, tmp_path, "validate") == 0
    assert "Validation passed." in capsys.readouterr().out


def test_the_history_is_in_the_archive_file(tmp_path, monkeypatch) -> None:
    """The goal, the tasks and the records are all there."""
    _project(monkeypatch, tmp_path)
    goal, tasks = _goal(tmp_path)

    assert _archive_goal(monkeypatch, tmp_path, goal) == 0

    entry = _archive(tmp_path).get_entry(goal.id)

    assert entry.goal == goal
    assert entry.tasks == tuple(tasks)
    assert [record.task_id for record in entry.records] == [
        task.id for task in tasks
    ]
    assert entry.reason == "tidy up"


def test_a_goal_with_work_in_flight_is_refused(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The unfinished tasks are listed, and no file changes."""
    _project(monkeypatch, tmp_path)
    goal, tasks = _goal(tmp_path, ("completed", "ready", "running"))
    before = {
        path.name: path.read_bytes() for path in tmp_path.glob("*.json")
    }
    capsys.readouterr()

    assert _archive_goal(monkeypatch, tmp_path, goal) == 1

    output = capsys.readouterr().out

    assert f"Error: goal {goal.id} has 2 tasks that are not finished" in output
    assert "Tasks that are not finished: 2" in output
    assert f"- {tasks[1].id} (ready)" in output
    assert f"- {tasks[2].id} (running)" in output
    assert "Nothing was changed." in output
    assert {
        path.name: path.read_bytes() for path in tmp_path.glob("*.json")
    } == before
    assert not (tmp_path / "archive.json").exists()


def test_only_the_first_unfinished_tasks_are_listed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Seven are counted, five are shown, and two are summed up."""
    _project(monkeypatch, tmp_path)
    goal, tasks = _goal(tmp_path, ("ready",) * 7)
    capsys.readouterr()

    assert _archive_goal(monkeypatch, tmp_path, goal) == 1

    output = capsys.readouterr().out

    assert "Tasks that are not finished: 7" in output
    assert "  and 2 more" in output
    assert sum(1 for task in tasks if f"- {task.id} " in output) == 5


def test_five_unfinished_tasks_are_listed_with_no_summary(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Nothing is hidden, so nothing is said to be left out."""
    _project(monkeypatch, tmp_path)
    goal, tasks = _goal(tmp_path, ("ready",) * 5)
    capsys.readouterr()

    assert _archive_goal(monkeypatch, tmp_path, goal) == 1

    output = capsys.readouterr().out

    assert "Tasks that are not finished: 5" in output
    assert all(f"- {task.id} " in output for task in tasks)
    assert " more" not in output


def test_spaces_around_the_goal_id_are_ignored(tmp_path, monkeypatch) -> None:
    """The id is trimmed, as the other commands trim what they are given."""
    _project(monkeypatch, tmp_path)
    goal, _ = _goal(tmp_path)

    result = run_cli(
        monkeypatch,
        tmp_path,
        "goal",
        "archive",
        f"  {goal.id}  ",
        "--reason",
        "tidy up",
    )

    assert result == 0
    assert _archive(tmp_path).has_goal(goal.id) is True


def test_a_reason_is_required(tmp_path, monkeypatch) -> None:
    """Leaving it out is a usage error."""
    _project(monkeypatch, tmp_path)
    goal, _ = _goal(tmp_path)

    with pytest.raises(SystemExit) as caught:
        run_cli(monkeypatch, tmp_path, "goal", "archive", goal.id)

    assert caught.value.code == 2
    assert GoalRegistry(tmp_path / "goals.json").get_goal(goal.id) == goal


def test_a_blank_reason_is_refused(tmp_path, monkeypatch, capsys) -> None:
    """The error says so, and nothing is changed."""
    _project(monkeypatch, tmp_path)
    goal, _ = _goal(tmp_path)
    capsys.readouterr()

    assert _archive_goal(monkeypatch, tmp_path, goal, "   ") == 1

    assert "archive reason cannot be empty" in capsys.readouterr().out
    assert not (tmp_path / "archive.json").exists()


def test_an_unknown_goal_is_refused(tmp_path, monkeypatch, capsys) -> None:
    """The error names the id."""
    _project(monkeypatch, tmp_path)
    capsys.readouterr()

    result = run_cli(
        monkeypatch,
        tmp_path,
        "goal",
        "archive",
        "nope",
        "--reason",
        "x",
    )

    assert result == 1
    assert "Error: goal not found: nope" in capsys.readouterr().out


def test_archiving_again_changes_nothing(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The second run says that the goal is already archived."""
    _project(monkeypatch, tmp_path)
    goal, _ = _goal(tmp_path)
    assert _archive_goal(monkeypatch, tmp_path, goal) == 0
    before = (tmp_path / "archive.json").read_bytes()
    capsys.readouterr()

    assert _archive_goal(monkeypatch, tmp_path, goal, "second") == 0

    assert f"Goal already archived: {goal.id}" in capsys.readouterr().out
    assert (tmp_path / "archive.json").read_bytes() == before


def test_archiving_lets_the_project_be_removed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """This is what the archive is for, and the history keeps the directory."""
    directory = _project(monkeypatch, tmp_path)
    goal, _ = _goal(tmp_path)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 1
    assert _archive_goal(monkeypatch, tmp_path, goal) == 0
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 0
    assert "Project removed: app" in capsys.readouterr().out

    entry = _archive(tmp_path).get_entry(goal.id)

    assert entry.project_path == str(directory.resolve())

    other = _project(monkeypatch, tmp_path / "again")

    assert other != directory
    assert _archive(tmp_path).get_entry(goal.id) == entry


def test_a_crash_leaves_a_state_that_validate_reports_and_archiving_repairs(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The same command finishes what a crash left, with the first reason."""
    _project(monkeypatch, tmp_path)
    goal, _ = _goal(tmp_path)
    capsys.readouterr()

    def boom(self, task_ids):
        raise OSError("crash")

    with monkeypatch.context() as patch:
        patch.setattr(TaskRegistry, "remove_tasks", boom)

        with pytest.raises(OSError):
            _archive_goal(monkeypatch, tmp_path, goal, "first reason")

    assert _archive(tmp_path).has_goal(goal.id) is True
    assert run_cli(monkeypatch, tmp_path, "validate") == 1
    assert "archived and also still active" in capsys.readouterr().out

    assert _archive_goal(monkeypatch, tmp_path, goal, "second reason") == 0

    output = capsys.readouterr().out

    assert f"Goal archive finished: {goal.id}" in output
    assert "Reason: first reason" in output
    assert run_cli(monkeypatch, tmp_path, "validate") == 0
    assert "Validation passed." in capsys.readouterr().out


def test_an_archived_task_is_no_longer_found_by_task_history(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """This is a cost of archiving, and a listing is a later stage."""
    _project(monkeypatch, tmp_path)
    goal, tasks = _goal(tmp_path)
    assert _archive_goal(monkeypatch, tmp_path, goal) == 0
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "task", "history", tasks[0].id) == 1
    assert "not found" in capsys.readouterr().out.lower()
