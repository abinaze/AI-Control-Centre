"""Tests for aic task running."""

import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from aic_control_centre import locking
from aic_control_centre.cli import main
from aic_control_centre.execution.records import ExecutionRecord
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
EARLIER = "2026-10-19T09:00:00+00:00"


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    """Make the command see a fixed time, not the real one."""
    monkeypatch.setattr("aic_control_centre.tasks.commands._now", lambda: NOW)


def _task(task_id, status="running", updated_at=EARLIER):
    return Task(
        id=task_id,
        goal_id="goal-1",
        title=f"title {task_id}",
        description="",
        status=status,
        created_at="2026-10-01T00:00:00+00:00",
        updated_at=updated_at,
    )


def _record(task_id, started_at=EARLIER, source="cli", target=None):
    return ExecutionRecord(
        id=f"record-{task_id}",
        task_id=task_id,
        source=source,
        target=target,
        started_at=started_at,
        ended_at=None,
        ended_as=None,
        reason="",
    )


def _state(tmp_path, tasks, records=()):
    write_text_atomic(
        tmp_path / "tasks.json",
        serialize_state_items("tasks", [asdict(task) for task in tasks]),
    )

    if records:
        write_text_atomic(
            tmp_path / "executions.json",
            serialize_state_items(
                "executions",
                [asdict(record) for record in records],
            ),
        )


def test_it_says_when_nothing_is_running(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """An empty state prints a plain message, and writes nothing."""
    assert run_cli(monkeypatch, tmp_path, "task", "running") == 0

    assert capsys.readouterr().out.strip() == "No running tasks."
    assert list(tmp_path.iterdir()) == []


def test_it_lists_a_running_task_with_how_long_it_has_run(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Each task shows what a person needs to decide."""
    _state(tmp_path, [_task("t1")], [_record("t1")])

    assert run_cli(monkeypatch, tmp_path, "task", "running") == 0

    output = capsys.readouterr().out

    assert "Running tasks: 1" in output
    assert "- t1" in output
    assert "  Title: title t1" in output
    assert "  Goal: goal-1" in output
    assert "  Route: cli" in output
    assert "  Since: 2026-10-19T09:00:00+00:00" in output
    assert "  Running for: 3h 0m" in output
    assert "estimated" not in output


def test_it_ends_with_the_warning_and_the_requeue_command(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The risk is stated next to the way out."""
    _state(tmp_path, [_task("t1")], [_record("t1")])

    run_cli(monkeypatch, tmp_path, "task", "running")

    output = capsys.readouterr().out

    assert (
        "A task listed here may still be running. "
        "Requeueing a live run runs the task twice."
    ) in output
    assert (
        'To put a task back in the queue: '
        'aic task requeue <task-id> --reason "<text>"'
    ) in output
    assert "dead" not in output
    assert "stale" not in output


def test_it_shows_the_target_of_a_coordinator_attempt(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The route says how the run was started."""
    _state(
        tmp_path,
        [_task("t1")],
        [_record("t1", source="coordinator", target="process")],
    )

    run_cli(monkeypatch, tmp_path, "task", "running")

    assert "  Route: coordinator (process)" in capsys.readouterr().out


def test_a_task_with_no_attempt_is_marked_as_an_estimate(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A task from before records existed is timed from its last update."""
    _state(tmp_path, [_task("t1", updated_at="2026-10-16T06:00:00+00:00")])

    run_cli(monkeypatch, tmp_path, "task", "running")

    output = capsys.readouterr().out

    assert "  Route: unknown (before records existed)" in output
    assert (
        "  Since: 2026-10-16T06:00:00+00:00 "
        "(estimated from the last update)"
    ) in output
    assert "  Running for: 3d 6h" in output


def test_only_running_tasks_are_listed_longest_first(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Other statuses are left out, and the oldest comes first."""
    tasks = [
        _task("new"),
        _task("done", status="completed"),
        _task("old"),
        _task("waiting", status="ready"),
    ]
    records = [
        _record("new", started_at="2026-10-19T11:00:00+00:00"),
        _record("old", started_at="2026-10-18T11:00:00+00:00"),
    ]
    _state(tmp_path, tasks, records)

    run_cli(monkeypatch, tmp_path, "task", "running")

    output = capsys.readouterr().out

    assert "Running tasks: 2" in output
    assert output.index("- old") < output.index("- new")
    assert "- done" not in output
    assert "- waiting" not in output


def test_older_than_filters_the_listing(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Only tasks that have run for at least that long are listed."""
    tasks = [_task("old"), _task("new")]
    records = [
        _record("old", started_at="2026-10-19T06:00:00+00:00"),
        _record("new", started_at="2026-10-19T11:30:00+00:00"),
    ]
    _state(tmp_path, tasks, records)

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "running",
        "--older-than",
        "2h",
    )

    output = capsys.readouterr().out

    assert result == 0
    assert "Running tasks: 1" in output
    assert "- old" in output
    assert "- new" not in output


def test_older_than_says_so_when_nothing_matches(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The message repeats the limit that was asked for."""
    _state(tmp_path, [_task("t1")], [_record("t1")])

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "running",
        "--older-than",
        "1d",
    )

    assert result == 0
    assert capsys.readouterr().out.strip() == "No running tasks older than 1d."


@pytest.mark.parametrize("text", ["0m", "-5m", "5", "5w", "m", "1.5h", ""])
def test_a_bad_duration_is_refused_before_anything_is_printed(
    tmp_path,
    monkeypatch,
    capsys,
    text,
) -> None:
    """The message is the only output, and the exit status is 1."""
    _state(tmp_path, [_task("t1")], [_record("t1")])

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "running",
        f"--older-than={text}",
    )

    output = capsys.readouterr().out

    assert result == 1
    assert output.startswith("Error: ")
    assert output.count("\n") == 1
    assert "Running tasks" not in output


def test_a_start_time_in_the_future_is_shown_as_such(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A clock that moved back is reported and not hidden."""
    _state(
        tmp_path,
        [_task("t1")],
        [_record("t1", started_at="2026-10-19T18:00:00+00:00")],
    )

    run_cli(monkeypatch, tmp_path, "task", "running")

    assert (
        "  Running for: 0s (the start time is in the future)"
        in capsys.readouterr().out
    )


def test_a_start_time_that_cannot_be_read_is_shown_and_kept_by_the_filter(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Bad data never hides a task, even from a filter."""
    _state(
        tmp_path,
        [_task("t1")],
        [_record("t1", started_at="garbage")],
    )

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "running",
        "--older-than",
        "30d",
    )

    output = capsys.readouterr().out

    assert result == 0
    assert "  Since: garbage" in output
    assert "  Running for: unknown (the start time cannot be read)" in output


def test_the_command_never_modifies_the_state_files(
    tmp_path,
    monkeypatch,
) -> None:
    """Both files are identical afterwards."""
    _state(tmp_path, [_task("t1"), _task("t2")], [_record("t1")])
    before = {
        name: (tmp_path / name).read_bytes()
        for name in ("tasks.json", "executions.json")
    }

    run_cli(monkeypatch, tmp_path, "task", "running")
    run_cli(monkeypatch, tmp_path, "task", "running", "--older-than", "1m")

    assert {name: (tmp_path / name).read_bytes() for name in before} == before


def test_the_command_runs_while_the_lock_is_held(
    tmp_path,
    monkeypatch,
    capsys,
    start_lock_holder,
) -> None:
    """It is read-only, so it does not wait for the lock."""
    _state(tmp_path, [_task("t1")], [_record("t1")])
    start_lock_holder(tmp_path)
    monkeypatch.setattr(locking, "DEFAULT_LOCK_TIMEOUT", 0.3)

    assert run_cli(monkeypatch, tmp_path, "task", "running") == 0
    assert "- t1" in capsys.readouterr().out


def test_an_unreadable_state_file_is_reported(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A damaged task file ends the command with an error message."""
    (tmp_path / "tasks.json").write_text("{not json", encoding="utf-8")

    assert run_cli(monkeypatch, tmp_path, "task", "running") == 1
    assert "tasks.json" in capsys.readouterr().out


def test_a_task_started_through_the_cli_is_listed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A real start leaves a record that the command reads."""
    monkeypatch.undo()
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

    assert run_cli(monkeypatch, tmp_path, "task", "running") == 0

    output = capsys.readouterr().out

    assert f"- {task.id}" in output
    assert "  Route: cli" in output
    assert re.search(r"  Running for: \d+s", output)
    assert "estimated" not in output
