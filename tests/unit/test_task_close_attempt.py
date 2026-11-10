"""Tests for aic task close-attempt."""

import json
import os
import re
import sys

import pytest

from aic_control_centre.cli import main
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.execution.run_lock import (
    RUN_LOCK_SUFFIX,
    RUNS_DIR_NAME,
    hold_run_lock,
)
from aic_control_centre.storage import StateFileError


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _id(output):
    return re.search(r"^ID: (\S+)", output, re.M).group(1)


def _failing_close(self, *args, **kwargs):
    raise StateFileError("executions.json cannot be written: simulated")


def _stuck(tmp_path, monkeypatch, capsys, finish="complete"):
    """Finish a task while the close of its attempt fails.

    This is the state that G11 describes: the task is final and its
    attempt is still open. The failing write is simulated.
    """
    data = tmp_path / "data"
    project = tmp_path / "project"
    data.mkdir()
    project.mkdir()

    assert run_cli(monkeypatch, data, "project", "add", str(project)) == 0
    assert run_cli(
        monkeypatch, data, "goal", "create", "--project", project.name, "g",
    ) == 0
    goal = _id(capsys.readouterr().out)
    assert run_cli(
        monkeypatch, data, "task", "create", "--goal", goal, "the task",
    ) == 0
    task = _id(capsys.readouterr().out)
    assert run_cli(monkeypatch, data, "task", "ready", task) == 0
    assert run_cli(monkeypatch, data, "task", "start", task) == 0

    with monkeypatch.context() as patched:
        patched.setattr(
            ExecutionRecordRegistry,
            "close_attempt",
            _failing_close,
        )

        result = run_cli(
            patched, data, "task", finish, task, "--reason", "done",
        )

    assert result == 1
    capsys.readouterr()

    return data, goal, task


def _close(monkeypatch, data, task, reason="the write failed"):
    return run_cli(
        monkeypatch, data, "task", "close-attempt", task, "--reason", reason,
    )


def _state(data):
    return {
        name: (data / name).read_bytes()
        for name in sorted(os.listdir(data))
        if os.path.isfile(data / name) and not name.startswith(".")
    }


def _attempt_id(data, task):
    records = ExecutionRecordRegistry.beside(data / "tasks.json")

    return records.list_attempts(task)[0].id


@pytest.mark.parametrize(
    ("finish", "outcome"),
    [("complete", "completed"), ("fail", "failed")],
)
def test_the_command_closes_the_attempt_that_a_failed_write_left(
    tmp_path,
    monkeypatch,
    capsys,
    finish,
    outcome,
) -> None:
    data, goal, task = _stuck(tmp_path, monkeypatch, capsys, finish)
    attempt = _attempt_id(data, task)

    assert run_cli(monkeypatch, data, "validate") == 1
    assert "is open but task" in capsys.readouterr().out

    tasks_before = (data / "tasks.json").read_bytes()
    goals_before = (data / "goals.json").read_bytes()

    assert _close(monkeypatch, data, task) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"Attempt closed: {attempt}",
        f"Task: {task}",
        f"Outcome: {outcome}",
        "Reason: closed afterwards: the write failed",
    ]
    assert (data / "tasks.json").read_bytes() == tasks_before
    assert (data / "goals.json").read_bytes() == goals_before
    assert run_cli(monkeypatch, data, "validate") == 0


def test_the_goal_can_be_archived_after_the_attempt_is_closed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, task = _stuck(tmp_path, monkeypatch, capsys)

    assert run_cli(
        monkeypatch, data, "goal", "archive", "--reason", "done", goal,
    ) == 1
    assert "is still open" in capsys.readouterr().out

    assert _close(monkeypatch, data, task) == 0
    capsys.readouterr()

    assert run_cli(
        monkeypatch, data, "goal", "archive", "--reason", "done", goal,
    ) == 0


def test_the_history_shows_that_the_attempt_was_closed_afterwards(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, task = _stuck(tmp_path, monkeypatch, capsys)

    run_cli(monkeypatch, data, "task", "history", task)
    before = capsys.readouterr().out

    _close(monkeypatch, data, task)
    capsys.readouterr()

    run_cli(monkeypatch, data, "task", "history", task)
    after = capsys.readouterr().out

    assert "still open" in before
    assert "still open" not in after
    assert "closed afterwards: the write failed" in after


def test_the_command_leaves_the_goal_to_aic_goal_status(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, task = _stuck(tmp_path, monkeypatch, capsys)
    goals = json.loads((data / "goals.json").read_text(encoding="utf-8"))
    goals["goals"][0]["status"] = "in_progress"
    (data / "goals.json").write_text(json.dumps(goals), encoding="utf-8")

    assert _close(monkeypatch, data, task) == 0
    capsys.readouterr()

    stored = json.loads((data / "goals.json").read_text(encoding="utf-8"))

    assert stored["goals"][0]["status"] == "in_progress"
    assert run_cli(monkeypatch, data, "validate") == 1
    assert "status mismatch" in capsys.readouterr().out

    assert run_cli(monkeypatch, data, "goal", "status", goal) == 0
    assert run_cli(monkeypatch, data, "validate") == 0


def test_a_running_task_is_refused_and_nothing_is_written(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, task = _stuck(tmp_path, monkeypatch, capsys)
    run_cli(monkeypatch, data, "goal", "create", "--project", "project", "g2")
    second_goal = _id(capsys.readouterr().out)
    run_cli(
        monkeypatch, data, "task", "create", "--goal", second_goal, "second",
    )
    second = _id(capsys.readouterr().out)
    run_cli(monkeypatch, data, "task", "ready", second)
    run_cli(monkeypatch, data, "task", "start", second)
    capsys.readouterr()
    before = _state(data)

    assert _close(monkeypatch, data, second) == 1

    assert capsys.readouterr().out.strip() == (
        f"Error: task {second} is running; finish it with aic task "
        "complete, aic task fail or aic task requeue."
    )
    assert _state(data) == before


def test_a_task_with_no_open_attempt_is_refused(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, task = _stuck(tmp_path, monkeypatch, capsys)

    assert _close(monkeypatch, data, task) == 0
    capsys.readouterr()
    before = _state(data)

    assert _close(monkeypatch, data, task, reason="again") == 1

    assert capsys.readouterr().out.strip() == (
        f"Error: task {task} has no open attempt."
    )
    assert _state(data) == before


def test_an_unknown_task_and_a_blank_reason_are_refused(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, task = _stuck(tmp_path, monkeypatch, capsys)
    before = _state(data)

    assert _close(monkeypatch, data, "no-such-task") == 1
    assert capsys.readouterr().out.strip() == (
        "Error: task not found: no-such-task"
    )

    assert _close(monkeypatch, data, task, reason="   ") == 1
    assert capsys.readouterr().out.strip() == (
        "Error: a reason is required to close an attempt."
    )
    assert _state(data) == before


def test_the_reason_option_is_required(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, task = _stuck(tmp_path, monkeypatch, capsys)

    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch, data, "task", "close-attempt", task)

    assert stopped.value.code == 2
    assert "--reason" in capsys.readouterr().err


def test_a_run_that_is_alive_is_refused(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, task = _stuck(tmp_path, monkeypatch, capsys)
    attempt = _attempt_id(data, task)
    before = _state(data)

    with hold_run_lock(data, attempt):
        assert _close(monkeypatch, data, task) == 1

    output = capsys.readouterr().out

    assert output.startswith(f"Error: the run of task {task} is still alive")
    assert _state(data) == before


def test_the_lock_file_of_a_gone_owner_is_removed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, task = _stuck(tmp_path, monkeypatch, capsys)
    attempt = _attempt_id(data, task)
    runs = data / RUNS_DIR_NAME
    runs.mkdir()
    (runs / (attempt + RUN_LOCK_SUFFIX)).write_bytes(b"")

    assert _close(monkeypatch, data, task) == 0

    assert os.listdir(runs) == []


def test_the_command_takes_the_state_lock(
    tmp_path,
    monkeypatch,
    capsys,
    start_lock_holder,
) -> None:
    data, goal, task = _stuck(tmp_path, monkeypatch, capsys)
    before = _state(data)
    start_lock_holder(data)
    monkeypatch.setattr("aic_control_centre.locking.DEFAULT_LOCK_TIMEOUT", 0.3)

    assert _close(monkeypatch, data, task) == 1

    assert _state(data) == before


def test_the_help_lists_the_command(monkeypatch, capsys, tmp_path) -> None:
    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch, tmp_path, "task", "--help")

    assert stopped.value.code == 0
    assert "close-attempt" in capsys.readouterr().out
