"""Tests for aic task run with a target that acts on a project directory."""

import shutil
import sys

from aic_control_centre.cli import main
from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.process import ProcessAdapter
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry

PATH_CHILD = """
import json, sys
request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
print(json.dumps({"outcome": "completed",
                  "reason": request["project_path"]}))
"""


class NeedsProject:
    """An adapter that acts on the project directory. It keeps its requests."""

    requires_grant = False
    requires_project = True

    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)

        return ExecutionOutcome(
            task_id=request.task_id,
            outcome="completed",
            reason="inspected",
        )


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _task(tmp_path):
    """Register a project directory, a goal and a ready task."""
    project = tmp_path / "project"
    project.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(project)
    goal = Goal.create(description="Project goal", project="project")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Project task")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    return task, project.resolve()


def _offer(monkeypatch, adapter):
    adapters = ExecutionAdapterRegistry()
    adapters.register("inspect", adapter)
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.build_adapter_registry",
        lambda: adapters,
    )


def _run(monkeypatch, tmp_path, task, target="inspect"):
    return run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        target,
    )


def _status(tmp_path, task):
    return TaskRegistry(tmp_path / "tasks.json").get_task(task.id).status


def test_run_gives_the_adapter_the_registered_path(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The path in the registry reaches the adapter."""
    task, project = _task(tmp_path)
    adapter = NeedsProject()
    _offer(monkeypatch, adapter)

    result = _run(monkeypatch, tmp_path, task)

    assert result == 0
    assert "Result: completed" in capsys.readouterr().out
    assert [request.project_path for request in adapter.requests] == [project]


def test_run_is_refused_when_the_directory_is_gone(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Nothing runs and nothing is written for a deleted directory."""
    task, project = _task(tmp_path)
    adapter = NeedsProject()
    _offer(monkeypatch, adapter)
    shutil.rmtree(project)

    result = _run(monkeypatch, tmp_path, task)

    output = capsys.readouterr().out

    assert result == 1
    assert "Result: rejected" in output
    assert "does not exist" in output
    assert adapter.requests == []
    assert _status(tmp_path, task) == "ready"
    assert not (tmp_path / "executions.json").exists()


def test_run_is_refused_when_the_path_is_a_file(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A file where the directory was is not a project."""
    task, project = _task(tmp_path)
    adapter = NeedsProject()
    _offer(monkeypatch, adapter)
    shutil.rmtree(project)
    project.write_text("a file now", encoding="utf-8")

    result = _run(monkeypatch, tmp_path, task)

    assert result == 1
    assert "is not a directory" in capsys.readouterr().out
    assert adapter.requests == []
    assert _status(tmp_path, task) == "ready"


def test_run_is_refused_when_the_project_is_not_registered(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A goal that names a project that is no longer registered is refused."""
    task, _ = _task(tmp_path)
    adapter = NeedsProject()
    _offer(monkeypatch, adapter)
    write_text_atomic(
        tmp_path / "projects.json",
        serialize_state_items("projects", []),
    )

    result = _run(monkeypatch, tmp_path, task)

    assert result == 1
    assert "project project is not registered" in capsys.readouterr().out
    assert adapter.requests == []
    assert _status(tmp_path, task) == "ready"


def test_noop_still_runs_when_the_directory_is_gone(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The noop target needs no project, so its behaviour is unchanged."""
    task, project = _task(tmp_path)
    shutil.rmtree(project)

    result = _run(monkeypatch, tmp_path, task, target="noop")

    assert result == 0
    assert "Result: completed" in capsys.readouterr().out
    assert _status(tmp_path, task) == "completed"


def test_a_child_process_receives_the_path_on_standard_input(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The recorded reason is the path that the child read from its input."""
    task, project = _task(tmp_path)
    _offer(
        monkeypatch,
        ProcessAdapter(
            [sys.executable, "-c", PATH_CHILD],
            requires_grant=False,
            requires_project=True,
        ),
    )

    result = _run(monkeypatch, tmp_path, task)

    attempts = ExecutionRecordRegistry.beside(
        tmp_path / "tasks.json",
    ).list_attempts(task.id)

    assert result == 0
    assert attempts[0].reason == str(project)
