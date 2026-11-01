"""Tests for aic goal archived."""

import sys
from dataclasses import replace

from aic_control_centre.cli import main
from aic_control_centre.execution.records import ExecutionRecordRegistry
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


def _goal(tmp_path, project="app", status="completed", tasks=2, records=None):
    """Add a finished goal with finished tasks, and records for some."""
    goal = replace(Goal.create(f"Work on {project}", project), status=status)
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    registry = TaskRegistry(tmp_path / "tasks.json")
    history = ExecutionRecordRegistry.beside(registry.registry_path)
    kept = tasks if records is None else records

    for number in range(tasks):
        task = replace(
            Task.create(goal.id, f"task {number}"),
            status="completed",
        )
        registry.add_task(task)

        if number < kept:
            history.open_attempt(task.id, "coordinator", "noop")
            history.close_attempt(task.id, "completed", "why", "coordinator")

    return goal


def _archive(monkeypatch, tmp_path, goal, reason="tidy up"):
    code = run_cli(
        monkeypatch,
        tmp_path,
        "goal",
        "archive",
        goal.id,
        "--reason",
        reason,
    )

    assert code == 0


def _state(tmp_path):
    return {path.name: path.read_bytes() for path in tmp_path.glob("*.json")}


def test_nothing_archived_is_said_so_and_nothing_is_created(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Looking at an archive that is not there does not make it."""
    assert run_cli(monkeypatch, tmp_path, "goal", "archived") == 0

    assert "No archived goals." in capsys.readouterr().out
    assert not (tmp_path / "archive.json").exists()


def test_an_archived_goal_is_listed_with_what_was_kept(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The goal, its project and directory, the reason and the counts."""
    directory = _project(monkeypatch, tmp_path)
    goal = _goal(tmp_path, status="failed")
    _archive(monkeypatch, tmp_path, goal, "all shipped")
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "goal", "archived") == 0

    output = capsys.readouterr().out

    assert "Archived goals:" in output
    assert f"- {goal.id}" in output
    assert "  Project: app" in output
    assert f"  Directory: {directory.resolve()}" in output
    assert "  Status: failed" in output
    assert "  Description: Work on app" in output
    assert "  Reason: all shipped" in output
    assert "  Tasks: 2" in output
    assert "  Execution records: 2" in output
    assert "  Archived: 20" in output


def test_a_goal_whose_project_was_not_registered_has_no_directory(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The listing says that the directory was not recorded."""
    goal = _goal(tmp_path, project="elsewhere", tasks=0)
    _archive(monkeypatch, tmp_path, goal)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "goal", "archived") == 0

    output = capsys.readouterr().out

    assert "  Directory: not recorded" in output
    assert "  Tasks: 0" in output
    assert "  Execution records: 0" in output


def test_tasks_and_records_are_counted_separately(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A task that never ran has no record, so the two counts differ."""
    _project(monkeypatch, tmp_path)
    goal = _goal(tmp_path, tasks=3, records=1)
    _archive(monkeypatch, tmp_path, goal)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "goal", "archived") == 0

    output = capsys.readouterr().out

    assert "  Tasks: 3" in output
    assert "  Execution records: 1" in output


def test_every_archived_goal_is_listed_oldest_first(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """There is no limit, and the order is the order of archiving."""
    _project(monkeypatch, tmp_path)
    goals = [_goal(tmp_path) for _ in range(6)]

    for goal in goals:
        _archive(monkeypatch, tmp_path, goal)

    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "goal", "archived") == 0

    output = capsys.readouterr().out
    positions = [output.index(f"- {goal.id}") for goal in goals]

    assert positions == sorted(positions)
    assert output.count("  Reason: tidy up") == 6


def test_the_listing_changes_no_file(tmp_path, monkeypatch, capsys) -> None:
    """Every state file is the same bytes afterwards."""
    _project(monkeypatch, tmp_path)
    _archive(monkeypatch, tmp_path, _goal(tmp_path))
    before = _state(tmp_path)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "goal", "archived") == 0
    assert _state(tmp_path) == before


def test_the_directory_is_kept_when_the_project_is_removed_and_reused(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The history still says which directory the name meant."""
    directory = _project(monkeypatch, tmp_path)
    _archive(monkeypatch, tmp_path, _goal(tmp_path))

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 0

    other = tmp_path / "other" / "app"
    other.mkdir(parents=True)

    assert run_cli(monkeypatch, tmp_path, "project", "add", str(other)) == 0
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "goal", "archived") == 0

    output = capsys.readouterr().out

    assert f"  Directory: {directory.resolve()}" in output
    assert str(other.resolve()) not in output


def test_an_archive_that_cannot_be_read_is_an_error_and_is_kept(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """It is not shown as empty, and it is not changed."""
    path = tmp_path / "archive.json"
    path.write_bytes(b"{ not json")

    assert run_cli(monkeypatch, tmp_path, "goal", "archived") == 1

    output = capsys.readouterr().out

    assert "Error:" in output
    assert "is not valid JSON" in output
    assert path.read_bytes() == b"{ not json"
