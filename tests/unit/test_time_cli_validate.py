"""Tests for time checks in aic validate."""

import json
import sys

from aic_control_centre.cli import main
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _started_task(tmp_path, monkeypatch, capsys):
    """Make a project, a goal and a task, and start it through the CLI."""
    project = tmp_path / "alpha"
    project.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(project)
    goal = Goal.create(description="A goal", project="alpha")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="A task")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    assert run_cli(monkeypatch, tmp_path, "task", "start", task.id) == 0
    capsys.readouterr()

    return task


def _edit(tmp_path, name, key, change):
    path = tmp_path / name
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data[key][0])
    path.write_text(json.dumps(data), encoding="utf-8")


def test_state_made_by_real_commands_passes(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The times that the CLI writes are always readable."""
    _started_task(tmp_path, monkeypatch, capsys)

    assert run_cli(monkeypatch, tmp_path, "validate") == 0
    assert "Validation passed." in capsys.readouterr().out


def test_a_start_time_that_is_not_a_time_fails_validation(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The case that was reproduced: garbage no longer passes."""
    _started_task(tmp_path, monkeypatch, capsys)
    _edit(
        tmp_path,
        "executions.json",
        "executions",
        lambda record: record.update(started_at="garbage"),
    )

    result = run_cli(monkeypatch, tmp_path, "validate")

    output = capsys.readouterr().out

    assert result == 1
    assert "has a time that cannot be read in started_at: 'garbage'" in output
    assert "Validation passed." not in output


def test_a_task_time_with_no_offset_fails_validation(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A time with no offset is reported, whoever edited it."""
    task = _started_task(tmp_path, monkeypatch, capsys)
    _edit(
        tmp_path,
        "tasks.json",
        "tasks",
        lambda item: item.update(updated_at="2026-10-19T09:00:00"),
    )

    result = run_cli(monkeypatch, tmp_path, "validate")

    assert result == 1
    assert (
        f"Task {task.id} has a time that cannot be read in updated_at"
        in capsys.readouterr().out
    )


def test_validate_does_not_change_a_file_with_a_bad_time(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Reporting is not repairing."""
    _started_task(tmp_path, monkeypatch, capsys)
    _edit(
        tmp_path,
        "executions.json",
        "executions",
        lambda record: record.update(started_at="garbage"),
    )
    before = (tmp_path / "executions.json").read_bytes()

    run_cli(monkeypatch, tmp_path, "validate")

    assert (tmp_path / "executions.json").read_bytes() == before


def test_a_task_with_a_bad_time_is_still_listed_as_running(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Validation fails, and the listing still shows the task."""
    task = _started_task(tmp_path, monkeypatch, capsys)
    _edit(
        tmp_path,
        "executions.json",
        "executions",
        lambda record: record.update(started_at="garbage"),
    )

    assert run_cli(monkeypatch, tmp_path, "task", "running") == 0

    output = capsys.readouterr().out

    assert f"- {task.id}" in output
    assert "Running for: unknown (the start time cannot be read)" in output
