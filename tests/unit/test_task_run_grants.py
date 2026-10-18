"""Tests for aic task run with grants."""

import os
import subprocess
import sys

from aic_control_centre.cli import main
from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry

DRIVER = """
import sys

import aic_control_centre.tasks.commands as commands
from aic_control_centre.cli import main
from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.registry import ExecutionAdapterRegistry


class Granted:
    def execute(self, request):
        return ExecutionOutcome(
            task_id=request.task_id,
            outcome="completed",
            reason="granted run",
        )


adapters = ExecutionAdapterRegistry()
adapters.register("child", Granted())
commands.build_adapter_registry = lambda: adapters
sys.argv = ["aic", "task", "run", sys.argv[1], "--target", "child"]
sys.exit(main())
"""


class NeedsGrant:
    """An adapter that says nothing about grants, so it needs one."""

    def __init__(self):
        self.calls = 0

    def execute(self, request):
        self.calls += 1

        return ExecutionOutcome(
            task_id=request.task_id,
            outcome="completed",
            reason="ran with a grant",
        )


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _project(tmp_path, name="project"):
    path = tmp_path / name
    path.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(path)


def _ready_task(tmp_path, project="project"):
    goal = Goal.create(description="Granted goal", project=project)
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Granted task")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    return task


def _setup(tmp_path, monkeypatch):
    """Register a project and a ready task, and offer an adapter."""
    _project(tmp_path)
    task = _ready_task(tmp_path)
    adapter = NeedsGrant()
    adapters = ExecutionAdapterRegistry()
    adapters.register("child", adapter)
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.build_adapter_registry",
        lambda: adapters,
    )

    return task, adapter


def _run(monkeypatch, tmp_path, task):
    return run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "child",
    )


def _status(tmp_path, task):
    return TaskRegistry(tmp_path / "tasks.json").get_task(task.id).status


def test_run_is_refused_without_a_grant(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A target that needs a grant does not run, and nothing is written."""
    task, adapter = _setup(tmp_path, monkeypatch)

    result = _run(monkeypatch, tmp_path, task)

    output = capsys.readouterr().out

    assert result == 1
    assert "Result: rejected" in output
    assert "target child is not granted for project project" in output
    assert adapter.calls == 0
    assert _status(tmp_path, task) == "ready"
    assert not (tmp_path / "executions.json").exists()
    assert not (tmp_path / "permissions.json").exists()


def test_run_goes_ahead_with_a_grant(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A grant made through the registry lets the run start."""
    task, adapter = _setup(tmp_path, monkeypatch)
    PermissionRegistry(tmp_path / "permissions.json").grant(
        "project",
        "child",
        "trusted",
    )

    result = _run(monkeypatch, tmp_path, task)

    assert result == 0
    assert "Result: completed" in capsys.readouterr().out
    assert adapter.calls == 1
    assert _status(tmp_path, task) == "completed"


def test_run_is_refused_again_after_a_revoke(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A revoked grant no longer allows the next run."""
    task, adapter = _setup(tmp_path, monkeypatch)
    permissions = PermissionRegistry(tmp_path / "permissions.json")
    permissions.grant("project", "child", "trusted")
    permissions.revoke("project", "child")

    result = _run(monkeypatch, tmp_path, task)

    assert result == 1
    assert "is not granted for project project" in capsys.readouterr().out
    assert adapter.calls == 0
    assert _status(tmp_path, task) == "ready"


def test_a_grant_for_another_project_does_not_allow_the_run(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A grant belongs to one project."""
    task, adapter = _setup(tmp_path, monkeypatch)
    PermissionRegistry(tmp_path / "permissions.json").grant(
        "other",
        "child",
        "trusted",
    )

    result = _run(monkeypatch, tmp_path, task)

    assert result == 1
    assert adapter.calls == 0
    assert "Result: rejected" in capsys.readouterr().out


def test_a_grant_for_another_target_does_not_allow_the_run(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A grant belongs to one target."""
    task, adapter = _setup(tmp_path, monkeypatch)
    PermissionRegistry(tmp_path / "permissions.json").grant(
        "project",
        "other",
        "trusted",
    )

    result = _run(monkeypatch, tmp_path, task)

    assert result == 1
    assert adapter.calls == 0
    assert "Result: rejected" in capsys.readouterr().out


def test_an_unreadable_grants_file_stops_the_run(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A damaged grants file is an error, never a quiet permission."""
    task, adapter = _setup(tmp_path, monkeypatch)
    (tmp_path / "permissions.json").write_text("{not json", encoding="utf-8")

    result = _run(monkeypatch, tmp_path, task)

    assert result == 1
    assert "Error:" in capsys.readouterr().out
    assert adapter.calls == 0
    assert _status(tmp_path, task) == "ready"
    assert not (tmp_path / "executions.json").exists()


def test_noop_still_runs_without_a_grant(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The real noop target needs no grant and is not affected."""
    _project(tmp_path)
    task = _ready_task(tmp_path)

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "noop",
    )

    assert result == 0
    assert "Result: completed" in capsys.readouterr().out


def test_eight_runs_with_a_grant_all_complete(tmp_path) -> None:
    """Concurrent runs that each need the grant all go through."""
    _project(tmp_path)
    PermissionRegistry(tmp_path / "permissions.json").grant(
        "project",
        "child",
        "trusted",
    )
    tasks = [_ready_task(tmp_path) for _ in range(8)]
    environment = {**os.environ, "AIC_DATA_DIR": str(tmp_path)}
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", DRIVER, task.id],
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
    assert all(record.target == "child" for record in records)
    assert not any(record.is_open for record in records)
