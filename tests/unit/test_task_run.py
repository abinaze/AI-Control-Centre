"""Tests for aic task run and aic task targets."""

import os
import subprocess
import sys

import pytest

from aic_control_centre import locking
from aic_control_centre.cli import build_parser, main
from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.records import (
    EXECUTION_SOURCE_COORDINATOR,
    ExecutionRecordRegistry,
)
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry

NOOP_REASON = "noop adapter: no work was done"
LOCK_FILE = ".aic.lock"


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


class Scripted:
    """An adapter that does what the test tells it to."""

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
    """Make aic task run offer one adapter, under the target scripted."""
    registry = ExecutionAdapterRegistry()
    registry.register("scripted", adapter)
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.build_adapter_registry",
        lambda: registry,
    )


def _make_task(data_dir, status="ready", title="Run task", goal=None):
    if goal is None:
        goal = Goal.create(description="Run goal", project="TestProject")
        GoalRegistry(data_dir / "goals.json").add_goal(goal)

    task = Task.create(goal_id=goal.id, title=title)
    registry = TaskRegistry(data_dir / "tasks.json")
    registry.add_task(task)

    if status != "pending":
        registry.update_task_status(task.id, status)

    return task


def _attempts(data_dir, task_id):
    records = ExecutionRecordRegistry.beside(data_dir / "tasks.json")

    return records.list_attempts(task_id)


def _status(data_dir, task_id):
    return TaskRegistry(data_dir / "tasks.json").get_task(task_id).status


def test_run_with_the_noop_adapter_completes_the_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The whole path works from the command line."""
    task = _make_task(tmp_path)

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "noop",
    )

    output = capsys.readouterr().out
    attempts = _attempts(tmp_path, task.id)

    assert result == 0
    assert f"Task: {task.id}" in output
    assert "Target: noop" in output
    assert "Result: completed" in output
    assert f"Reason: {NOOP_REASON}" in output
    assert _status(tmp_path, task.id) == "completed"
    assert len(attempts) == 1
    assert attempts[0].source == EXECUTION_SOURCE_COORDINATOR
    assert attempts[0].target == "noop"
    assert attempts[0].ended_as == "completed"
    assert attempts[0].reason == NOOP_REASON
    assert (tmp_path / LOCK_FILE).exists()


@pytest.mark.parametrize(
    ("behavior", "reported"),
    [
        ("fails", "scripted fails"),
        ("raises", "execution adapter failed: boom"),
    ],
)
def test_run_reports_an_adapter_that_fails(
    tmp_path,
    monkeypatch,
    capsys,
    behavior,
    reported,
) -> None:
    """A failing adapter fails the task, exits 1 and says why."""
    task = _make_task(tmp_path)
    _use_adapter(monkeypatch, Scripted(behavior))

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "scripted",
    )

    output = capsys.readouterr().out
    attempts = _attempts(tmp_path, task.id)

    assert result == 1
    assert "Result: failed" in output
    assert f"Reason: {reported}" in output
    assert _status(tmp_path, task.id) == "failed"
    assert attempts[0].ended_as == "failed"
    assert attempts[0].reason == reported


def test_run_with_an_unknown_target_changes_nothing(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """An unknown target is refused before any state is touched."""
    task = _make_task(tmp_path)

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "nowhere",
    )

    output = capsys.readouterr().out

    assert result == 1
    assert "Result: rejected" in output
    assert "unknown execution target" in output
    assert _status(tmp_path, task.id) == "ready"
    assert not (tmp_path / "executions.json").exists()
    assert not (tmp_path / LOCK_FILE).exists()


def test_run_refuses_a_task_that_is_not_ready(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A task that is not ready is refused and nothing is recorded."""
    task = _make_task(tmp_path, status="pending")

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "noop",
    )

    assert result == 1
    assert "Result: rejected" in capsys.readouterr().out
    assert _status(tmp_path, task.id) == "pending"
    assert not (tmp_path / "executions.json").exists()


def test_run_needs_a_target() -> None:
    """The target is required, so a run never picks one by itself."""
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["task", "run", "task-123"])

    args = parser.parse_args(["task", "run", "task-123", "--target", "noop"])

    assert args.target == "noop"


def test_requeue_works_while_the_adapter_runs(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The lock is free during the run, so a person can still recover."""
    task = _make_task(tmp_path)
    requeued = []

    def operator():
        requeued.append(
            run_cli(
                monkeypatch,
                tmp_path,
                "task",
                "requeue",
                task.id,
                "--reason",
                "looks dead",
            ),
        )

    _use_adapter(monkeypatch, Scripted(during=operator))

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "scripted",
    )

    assert requeued == [0]
    assert result == 1
    assert "task status is ready" in capsys.readouterr().out
    assert _status(tmp_path, task.id) == "ready"
    assert [a.ended_as for a in _attempts(tmp_path, task.id)] == ["requeued"]


def test_run_fails_cleanly_while_the_lock_is_held(
    tmp_path,
    monkeypatch,
    capsys,
    start_lock_holder,
) -> None:
    """If the start cannot get the lock, nothing has happened."""
    task = _make_task(tmp_path)
    start_lock_holder(tmp_path)
    monkeypatch.setattr(locking, "DEFAULT_LOCK_TIMEOUT", 0.3)

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "noop",
    )

    output = capsys.readouterr().out

    assert result == 1
    assert (
        "Error: another aic process is using the state files (waited 0.3s)."
        in output
    )
    assert "adapter has run" not in output
    assert _status(tmp_path, task.id) == "ready"
    assert not (tmp_path / "executions.json").exists()


def test_run_keeps_the_task_running_if_the_outcome_cannot_be_recorded(
    tmp_path,
    monkeypatch,
    capsys,
    start_lock_holder,
) -> None:
    """The shape is the one a crash leaves, and requeue recovers it."""
    task = _make_task(tmp_path)
    holders = []

    def another_process_takes_the_lock():
        holders.append(start_lock_holder(tmp_path))

    _use_adapter(monkeypatch, Scripted(during=another_process_takes_the_lock))
    monkeypatch.setattr(locking, "DEFAULT_LOCK_TIMEOUT", 0.3)

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "scripted",
    )

    output = capsys.readouterr().out
    attempts = _attempts(tmp_path, task.id)

    assert result == 1
    assert "waited 0.3s" in output
    assert "The adapter has run, but its outcome was not recorded." in output
    assert "still running" in output
    assert _status(tmp_path, task.id) == "running"
    assert len(attempts) == 1
    assert attempts[0].is_open
    assert attempts[0].source == EXECUTION_SOURCE_COORDINATOR

    holders[0].kill()
    holders[0].wait()
    monkeypatch.setattr(locking, "DEFAULT_LOCK_TIMEOUT", 10.0)

    assert (
        run_cli(
            monkeypatch,
            tmp_path,
            "task",
            "requeue",
            task.id,
            "--reason",
            "outcome was not recorded",
        )
        == 0
    )
    assert _status(tmp_path, task.id) == "ready"


def test_targets_lists_the_registered_targets(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The shipped targets are listed with what they do."""
    assert run_cli(monkeypatch, tmp_path, "task", "targets") == 0

    output = capsys.readouterr().out

    assert "Execution targets: 1" in output
    assert "noop: completes the task at once; no work is done" in output


def test_targets_runs_while_the_lock_is_held(
    tmp_path,
    monkeypatch,
    capsys,
    start_lock_holder,
) -> None:
    """Listing targets is read-only, so it does not wait for the lock."""
    start_lock_holder(tmp_path)
    monkeypatch.setattr(locking, "DEFAULT_LOCK_TIMEOUT", 0.3)

    assert run_cli(monkeypatch, tmp_path, "task", "targets") == 0
    assert "noop" in capsys.readouterr().out


def test_concurrent_runs_complete_every_task(tmp_path, monkeypatch) -> None:
    """Eight aic task run processes at once lose no update."""
    project = tmp_path / "project"
    project.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(project)
    goal = Goal.create(description="Run goal", project="project")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    tasks = [
        _make_task(tmp_path, title=f"task {number}", goal=goal)
        for number in range(8)
    ]
    environment = {**os.environ, "AIC_DATA_DIR": str(tmp_path)}
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "aic_control_centre.cli",
                "task",
                "run",
                task.id,
                "--target",
                "noop",
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for task in tasks
    ]
    outputs = [process.communicate(timeout=120) for process in processes]

    assert [process.returncode for process in processes] == [0] * 8, outputs

    statuses = [
        task.status
        for task in TaskRegistry(tmp_path / "tasks.json").list_tasks()
    ]
    records = ExecutionRecordRegistry.beside(
        tmp_path / "tasks.json",
    ).list_records()

    assert statuses == ["completed"] * 8
    assert len(records) == 8
    assert all(record.target == "noop" for record in records)
    assert not any(record.is_open for record in records)
    assert run_cli(monkeypatch, tmp_path, "validate") == 0
