"""Tests for the hint that aic task history gives for an archived task."""

import sys
from dataclasses import replace

from aic_control_centre.cli import main
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.goals.archive import ArchiveEntry, GoalArchive
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _entry(tasks=2):
    goal = Goal.create("Ship it", "app")
    held = [
        replace(Task.create(goal.id, f"task {number}"), status="completed")
        for number in range(tasks)
    ]

    return ArchiveEntry.create(goal, held, [], "tidy up")


def test_the_archive_finds_the_entry_that_holds_a_task(tmp_path) -> None:
    """Every task of an entry leads back to that entry."""
    archive = GoalArchive(tmp_path / "archive.json")
    first, second = _entry(), _entry()
    archive.add_entry(first)
    archive.add_entry(second)

    assert archive.find_task_entry(first.tasks[1].id) == first
    assert archive.find_task_entry(second.tasks[0].id) == second


def test_the_archive_finds_nothing_for_a_task_it_does_not_hold(
    tmp_path,
) -> None:
    """An unknown task, and an archive that is not there, give None."""
    archive = GoalArchive(tmp_path / "archive.json")

    assert archive.find_task_entry("nope") is None
    assert not (tmp_path / "archive.json").exists()

    archive.add_entry(_entry())

    assert archive.find_task_entry("nope") is None


def test_an_archived_task_is_pointed_at_its_goal(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The error stands, and two lines say where the task is."""
    entry = _entry()
    GoalArchive(tmp_path / "archive.json").add_entry(entry)
    task = entry.tasks[0]

    assert run_cli(monkeypatch, tmp_path, "task", "history", task.id) == 1

    assert capsys.readouterr().out == (
        f"Error: task not found: {task.id}\n"
        f"The task is in the archive, in goal {entry.goal.id}.\n"
        f"Show it with: aic goal archived {entry.goal.id}\n"
    )


def test_a_task_that_is_nowhere_gets_no_hint(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Only the error, as before, even when the archive has other tasks."""
    GoalArchive(tmp_path / "archive.json").add_entry(_entry())

    assert run_cli(monkeypatch, tmp_path, "task", "history", "nope") == 1

    assert capsys.readouterr().out == "Error: task not found: nope\n"


def test_an_active_task_is_shown_and_the_archive_is_not_asked(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A task that is found never touches the archive."""
    task = Task.create("goal", "active")
    TaskRegistry(tmp_path / "tasks.json").add_task(task)
    (tmp_path / "archive.json").write_bytes(b"{ not json")

    assert run_cli(monkeypatch, tmp_path, "task", "history", task.id) == 0
    assert "No attempts recorded." in capsys.readouterr().out


def test_an_archive_that_cannot_be_read_gives_no_hint_and_is_kept(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The original error stands, and nothing is written."""
    path = tmp_path / "archive.json"
    path.write_bytes(b"{ not json")

    assert run_cli(monkeypatch, tmp_path, "task", "history", "nope") == 1

    assert capsys.readouterr().out == "Error: task not found: nope\n"
    assert path.read_bytes() == b"{ not json"


def test_a_goal_archived_through_the_cli_is_found_by_its_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The whole way: archive a goal, then ask for one of its tasks."""
    goal = Goal.create("Ship it", "app")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = replace(Task.create(goal.id, "only"), status="completed")
    TaskRegistry(tmp_path / "tasks.json").add_task(task)
    records = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")
    records.open_attempt(task.id, "coordinator", "noop")
    records.close_attempt(task.id, "completed", "ok", "coordinator")

    assert run_cli(
        monkeypatch,
        tmp_path,
        "goal",
        "archive",
        goal.id,
        "--reason",
        "done",
    ) == 0
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "task", "history", task.id) == 1

    output = capsys.readouterr().out

    assert f"The task is in the archive, in goal {goal.id}." in output
    assert f"Show it with: aic goal archived {goal.id}" in output
