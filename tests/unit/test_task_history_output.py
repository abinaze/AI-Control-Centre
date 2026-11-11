"""Tests that pin the exact output of aic task history."""

import sys
from dataclasses import replace

import pytest

from aic_control_centre.cli import main
from aic_control_centre.execution.records import (
    ExecutionRecord,
    ExecutionRecordRegistry,
)
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry

START = "2026-10-30T00:00:00+00:00"
END = "2026-10-30T00:00:01+00:00"


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _record(task, number, **fields):
    values = {
        "id": f"record-{number}",
        "task_id": task.id,
        "source": "coordinator",
        "target": "noop",
        "started_at": START,
        "ended_at": END,
        "ended_as": "completed",
        "reason": "",
    }
    values.update(fields)

    return ExecutionRecord(**values)


def _history(monkeypatch, tmp_path, capsys, status, build):
    """Store a task with the records that build makes, and show its history."""
    task = replace(Task.create("goal", "a task"), status=status)
    tasks = TaskRegistry(tmp_path / "tasks.json")
    tasks.add_task(task)
    records = ExecutionRecordRegistry.beside(tasks.registry_path)

    # The registry cannot make a record with fixed times, so it is told what
    # to hold, and the history is read back through the command.
    records._save(build(task))
    capsys.readouterr()

    code = run_cli(monkeypatch, tmp_path, "task", "history", task.id)

    return task, code, capsys.readouterr().out


def test_a_task_with_no_attempts(tmp_path, monkeypatch, capsys) -> None:
    """The output is the task, its status and one line."""
    task, code, out = _history(
        monkeypatch, tmp_path, capsys, "ready", lambda task: []
    )

    assert code == 0
    assert out == (
        f"Task: {task.id}\n"
        "Status: ready\n"
        "No attempts recorded.\n"
    )


def test_one_completed_attempt_with_a_target(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Route, times, outcome and reason, in that order."""
    task, code, out = _history(
        monkeypatch,
        tmp_path,
        capsys,
        "completed",
        lambda task: [_record(task, 1, reason="done")],
    )

    assert code == 0
    assert out == (
        f"Task: {task.id}\n"
        "Status: completed\n"
        "Attempts: 1\n"
        "\n"
        "Attempt 1\n"
        "  Route: coordinator (noop)\n"
        f"  Started: {START}\n"
        f"  Ended: {END}\n"
        "  Outcome: completed\n"
        "  Reason: done\n"
    )


def test_two_attempts_one_without_a_target_and_one_without_a_reason(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A missing target shortens the route, a missing reason has no line."""
    task, code, out = _history(
        monkeypatch,
        tmp_path,
        capsys,
        "completed",
        lambda task: [
            _record(
                task,
                1,
                source="cli",
                target=None,
                ended_as="failed",
                reason="gave up",
            ),
            _record(task, 2, target="inspect"),
        ],
    )

    assert code == 0
    assert out == (
        f"Task: {task.id}\n"
        "Status: completed\n"
        "Attempts: 2\n"
        "\n"
        "Attempt 1\n"
        "  Route: cli\n"
        f"  Started: {START}\n"
        f"  Ended: {END}\n"
        "  Outcome: failed\n"
        "  Reason: gave up\n"
        "\n"
        "Attempt 2\n"
        "  Route: coordinator (inspect)\n"
        f"  Started: {START}\n"
        f"  Ended: {END}\n"
        "  Outcome: completed\n"
    )


def test_a_record_from_before_records_had_a_start_time(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The start says that it is unknown."""
    task, code, out = _history(
        monkeypatch,
        tmp_path,
        capsys,
        "completed",
        lambda task: [_record(task, 1, started_at=None, target=None)],
    )

    assert code == 0
    assert "  Started: unknown (before records existed)\n" in out
    assert "  Route: coordinator\n" in out


def test_an_open_attempt_of_a_running_task_has_no_note(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The attempt is open because the task is running."""
    task, code, out = _history(
        monkeypatch,
        tmp_path,
        capsys,
        "running",
        lambda task: [_record(task, 1, ended_at=None, ended_as=None)],
    )

    assert code == 0
    assert out == (
        f"Task: {task.id}\n"
        "Status: running\n"
        "Attempts: 1\n"
        "\n"
        "Attempt 1\n"
        "  Route: coordinator (noop)\n"
        f"  Started: {START}\n"
        "  Ended: still open\n"
    )


def test_an_open_attempt_of_a_task_that_is_not_running_has_a_note(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The attempt was left open, and the output says so."""
    task, code, out = _history(
        monkeypatch,
        tmp_path,
        capsys,
        "ready",
        lambda task: [_record(task, 1, ended_at=None, ended_as=None)],
    )

    assert code == 0
    assert out == (
        f"Task: {task.id}\n"
        "Status: ready\n"
        "Attempts: 1\n"
        "\n"
        "Attempt 1\n"
        "  Route: coordinator (noop)\n"
        f"  Started: {START}\n"
        "  Ended: still open\n"
        "  Note: the task is not running, so this attempt was left open\n"
    )


def test_an_unknown_task_is_an_error(tmp_path, monkeypatch, capsys) -> None:
    """The error names the task."""
    code = run_cli(monkeypatch, tmp_path, "task", "history", "nope")

    assert code == 1
    assert capsys.readouterr().out == "Error: task not found: nope\n"


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_an_open_attempt_of_a_final_task_says_how_to_close_it(
    tmp_path,
    monkeypatch,
    capsys,
    status,
) -> None:
    """The output ends with the command that closes the attempt."""
    task, code, out = _history(
        monkeypatch,
        tmp_path,
        capsys,
        status,
        lambda task: [_record(task, 1, ended_at=None, ended_as=None)],
    )

    assert code == 0
    assert out == (
        f"Task: {task.id}\n"
        f"Status: {status}\n"
        "Attempts: 1\n"
        "\n"
        "Attempt 1\n"
        "  Route: coordinator (noop)\n"
        f"  Started: {START}\n"
        "  Ended: still open\n"
        "  Note: the task is not running, so this attempt was left open\n"
        f"  Close it with: aic task close-attempt {task.id} "
        '--reason "<text>"\n'
    )


def test_a_task_that_is_not_final_gets_no_close_line(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The next start closes a left-over attempt of a ready task."""
    task, code, out = _history(
        monkeypatch,
        tmp_path,
        capsys,
        "ready",
        lambda task: [_record(task, 1, ended_at=None, ended_as=None)],
    )

    assert code == 0
    assert "close-attempt" not in out
