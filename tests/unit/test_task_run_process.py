"""Tests for aic task run with an adapter that runs in a child process."""

import sys

from aic_control_centre.cli import main
from aic_control_centre.execution.process import ProcessAdapter
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry

ECHO_CHILD = """
import json, sys
request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
print(json.dumps({"outcome": "completed",
                  "reason": "ran " + request["task_id"]}))
"""


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _setup(tmp_path, monkeypatch, adapter):
    """Register a project, a goal and a ready task, and offer the adapter."""
    project = tmp_path / "project"
    project.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(project)
    goal = Goal.create(description="Process goal", project="project")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Process task")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    adapters = ExecutionAdapterRegistry()
    adapters.register("child", adapter)
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.build_adapter_registry",
        lambda: adapters,
    )

    return task


def test_run_with_a_child_process_adapter_completes_the_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A result from a child process is recorded like any other."""
    adapter = ProcessAdapter(
        [sys.executable, "-c", ECHO_CHILD],
        requires_grant=False,
    )
    task = _setup(tmp_path, monkeypatch, adapter)

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "child",
    )

    attempts = ExecutionRecordRegistry.beside(
        tmp_path / "tasks.json",
    ).list_attempts(task.id)

    assert result == 0
    assert f"Reason: ran {task.id}" in capsys.readouterr().out
    assert attempts[0].ended_as == "completed"
    assert attempts[0].reason == f"ran {task.id}"


def test_a_timed_out_run_fails_the_task_and_records_why(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The CLI stops a hung child, and the task and record say so."""
    adapter = ProcessAdapter(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        requires_grant=False,
        timeout_seconds=1,
    )
    task = _setup(tmp_path, monkeypatch, adapter)

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "child",
    )

    output = capsys.readouterr().out
    attempts = ExecutionRecordRegistry.beside(
        tmp_path / "tasks.json",
    ).list_attempts(task.id)
    stored = TaskRegistry(tmp_path / "tasks.json").get_task(task.id)

    assert result == 1
    assert "Result: failed" in output
    assert "adapter timed out after 1 seconds" in output
    assert stored.status == "failed"
    assert attempts[0].ended_as == "failed"
    assert attempts[0].reason == "adapter timed out after 1 seconds"
    assert run_cli(monkeypatch, tmp_path, "validate") == 0
