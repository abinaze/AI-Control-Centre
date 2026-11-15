"""Tests for aic task run on a project that is too large to snapshot."""

import sys

import pytest

from aic_control_centre.cli import main
from aic_control_centre.execution import snapshot as snapshot_module
from aic_control_centre.execution.adapters import (
    INSPECT_TARGET,
    NOOP_TARGET,
    PYSYNTAX_TARGET,
)
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry

FILES = 5
TOO_MUCH = (
    "which is too much to check before and after a read-only run; "
    "the files were counted until the limit was passed"
)
ADVICE = "register a directory with fewer files as the project"


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _task(tmp_path):
    """Register a project with 5 files in a folder, a goal and a task."""
    project = tmp_path / "project"
    (project / "pkg").mkdir(parents=True)

    for number in range(FILES):
        (project / "pkg" / f"f{number}.py").write_bytes(b"x = 1\n")

    ProjectRegistry(tmp_path / "projects.json").add_project(project)
    goal = Goal.create(description="Look at it", project="project")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Look at it")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    return task


def _grant(tmp_path, target):
    PermissionRegistry.beside(tmp_path / "tasks.json").grant(
        "project",
        target,
        "look at the files",
    )


def _run(monkeypatch, tmp_path, task, target):
    return run_cli(
        monkeypatch, tmp_path, "task", "run", task.id, "--target", target,
    )


def _status(tmp_path, task):
    return TaskRegistry(tmp_path / "tasks.json").get_task(task.id).status


def _goal_status(tmp_path, task):
    goal_id = TaskRegistry(tmp_path / "tasks.json").get_task(task.id).goal_id

    return GoalRegistry(tmp_path / "goals.json").get_goal(goal_id).status


@pytest.mark.parametrize("target", [INSPECT_TARGET, PYSYNTAX_TARGET])
def test_a_project_that_is_too_large_is_refused(
    tmp_path,
    monkeypatch,
    capsys,
    target,
) -> None:
    """The refusal gives the reason, and nothing is written."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", FILES - 1)
    task = _task(tmp_path)
    _grant(tmp_path, target)
    goal_before = _goal_status(tmp_path, task)
    capsys.readouterr()

    result = _run(monkeypatch, tmp_path, task, target)

    lines = capsys.readouterr().out.splitlines()

    assert result == 1
    assert lines == [
        f"Task: {task.id}",
        f"Target: {target}",
        "Result: rejected",
        f"Reason: project project has more than {FILES - 1} files, "
        f"{TOO_MUCH}; the folders with the most files so far: "
        f"pkg ({FILES}); {ADVICE}",
    ]
    assert _status(tmp_path, task) == "ready"
    assert _goal_status(tmp_path, task) == goal_before
    assert not (tmp_path / "executions.json").exists()
    assert not (tmp_path / "runs").exists()


def test_a_project_exactly_at_the_limit_is_run(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Five files are allowed by a limit of five."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", FILES)
    task = _task(tmp_path)
    _grant(tmp_path, INSPECT_TARGET)
    capsys.readouterr()

    result = _run(monkeypatch, tmp_path, task, INSPECT_TARGET)

    assert result == 0
    assert "Result: completed" in capsys.readouterr().out
    assert _status(tmp_path, task) == "completed"


def test_the_size_limit_refuses_a_project_too(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Five files of six bytes are over a limit of twenty-nine bytes."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_BYTES", 29)
    task = _task(tmp_path)
    _grant(tmp_path, INSPECT_TARGET)
    capsys.readouterr()

    result = _run(monkeypatch, tmp_path, task, INSPECT_TARGET)

    out = capsys.readouterr().out

    assert result == 1
    assert "project project has more than 29 bytes in files" in out
    assert _status(tmp_path, task) == "ready"


def test_a_refused_task_can_be_run_when_the_limit_allows_it(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The task is still ready, so the same task runs afterwards."""
    task = _task(tmp_path)
    _grant(tmp_path, INSPECT_TARGET)

    with monkeypatch.context() as patched:
        patched.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", FILES - 1)

        assert _run(patched, tmp_path, task, INSPECT_TARGET) == 1

    capsys.readouterr()

    assert _run(monkeypatch, tmp_path, task, INSPECT_TARGET) == 0
    assert _status(tmp_path, task) == "completed"


def test_noop_is_not_affected_by_the_size_of_the_project(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The noop target takes no snapshot, so it is not refused."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 1)
    task = _task(tmp_path)
    capsys.readouterr()

    result = _run(monkeypatch, tmp_path, task, NOOP_TARGET)

    assert result == 0
    assert _status(tmp_path, task) == "completed"


def test_a_missing_grant_is_refused_before_the_size_is_looked_at(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The refusal for a missing grant is the one that is given."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 1)
    task = _task(tmp_path)
    capsys.readouterr()

    result = _run(monkeypatch, tmp_path, task, INSPECT_TARGET)

    out = capsys.readouterr().out

    assert result == 1
    assert "Reason: target inspect is not granted for project project" in out
    assert "too much" not in out
