"""Tests for the run lock that aic task run holds while a run lasts."""

import os
import sys

import pytest

from aic_control_centre.cli import main
from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.run_lock import (
    OWNER_ALIVE,
    OWNER_UNKNOWN,
    RUNS_DIR_NAME,
    probe_run_lock,
)
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


class Scripted:
    """An adapter that does what the test tells it to."""

    requires_grant = False

    def __init__(self, behavior="completed", during=None):
        self.behavior = behavior
        self.during = during

    def execute(self, request):
        if self.during is not None:
            self.during()

        if self.behavior == "raises":
            raise RuntimeError("boom")

        outcome = "failed" if self.behavior == "fails" else "completed"

        return ExecutionOutcome(
            task_id=request.task_id,
            outcome=outcome,
            reason=f"scripted {self.behavior}",
        )


def _use_adapter(monkeypatch, adapter):
    registry = ExecutionAdapterRegistry()
    registry.register("scripted", adapter)
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.build_adapter_registry",
        lambda: registry,
    )


def _make_task(data_dir, status="ready"):
    goal = Goal.create(description="Run lock goal", project="TestProject")
    GoalRegistry(data_dir / "goals.json").add_goal(goal)

    task = Task.create(goal_id=goal.id, title="Run lock task")
    registry = TaskRegistry(data_dir / "tasks.json")
    registry.add_task(task)

    if status != "pending":
        registry.update_task_status(task.id, status)

    return task


def _attempts(data_dir, task_id):
    records = ExecutionRecordRegistry.beside(data_dir / "tasks.json")

    return records.list_attempts(task_id)


def _run(monkeypatch, data_dir, task):
    return run_cli(
        monkeypatch,
        data_dir,
        "task",
        "run",
        task.id,
        "--target",
        "scripted",
    )


def test_the_run_lock_is_held_while_the_adapter_runs(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task = _make_task(tmp_path)
    seen = {}

    def during():
        attempt = _attempts(tmp_path, task.id)[0]

        seen["id"] = attempt.id
        seen["listing"] = os.listdir(tmp_path / RUNS_DIR_NAME)
        seen["owner"] = probe_run_lock(tmp_path, attempt.id)

    _use_adapter(monkeypatch, Scripted(during=during))

    result = _run(monkeypatch, tmp_path, task)

    output = capsys.readouterr().out

    assert result == 0
    assert seen["owner"] == OWNER_ALIVE
    assert seen["listing"] == [seen["id"] + ".lock"]
    assert "Note:" not in output


def test_the_run_lock_is_gone_after_a_completed_run(
    tmp_path,
    monkeypatch,
) -> None:
    task = _make_task(tmp_path)

    _use_adapter(monkeypatch, Scripted())

    assert _run(monkeypatch, tmp_path, task) == 0

    attempt = _attempts(tmp_path, task.id)[0]

    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []
    assert probe_run_lock(tmp_path, attempt.id) == OWNER_UNKNOWN


@pytest.mark.parametrize("behavior", ["fails", "raises"])
def test_the_run_lock_is_gone_after_a_failed_run(
    tmp_path,
    monkeypatch,
    behavior,
) -> None:
    task = _make_task(tmp_path)

    _use_adapter(monkeypatch, Scripted(behavior))

    assert _run(monkeypatch, tmp_path, task) == 1
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []


def test_the_run_lock_is_gone_after_an_interrupted_run(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task = _make_task(tmp_path)

    def interrupt():
        raise KeyboardInterrupt

    _use_adapter(monkeypatch, Scripted(during=interrupt))

    assert _run(monkeypatch, tmp_path, task) == 130
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []

    attempt = _attempts(tmp_path, task.id)[0]

    assert attempt.ended_at is None
    assert "Interrupted." in capsys.readouterr().out


def test_a_run_that_cannot_make_its_lock_still_runs_and_says_so(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task = _make_task(tmp_path)
    blocker = tmp_path / RUNS_DIR_NAME
    blocker.write_text("not a directory", encoding="utf-8")

    _use_adapter(monkeypatch, Scripted())

    result = _run(monkeypatch, tmp_path, task)

    output = capsys.readouterr().out
    attempts = _attempts(tmp_path, task.id)
    note_lines = [
        line for line in output.splitlines() if line.startswith("Note: ")
    ]

    assert result == 0
    assert "Result: completed" in output
    assert "Reason: scripted completed" in output
    assert len(note_lines) == 1
    assert "no owner was recorded for this run" in note_lines[0]
    assert attempts[0].ended_as == "completed"
    assert attempts[0].reason == "scripted completed"
    assert blocker.read_text(encoding="utf-8") == "not a directory"


def test_a_run_that_is_refused_takes_no_lock(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task = _make_task(tmp_path, status="pending")

    _use_adapter(monkeypatch, Scripted())

    result = _run(monkeypatch, tmp_path, task)

    assert result == 1
    assert not os.path.lexists(tmp_path / RUNS_DIR_NAME)
    assert _attempts(tmp_path, task.id) == []
    assert "Note:" not in capsys.readouterr().out
