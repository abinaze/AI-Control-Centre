"""Tests for aic task run with the shipped inspect target."""

import shutil
import sys

from aic_control_centre.cli import main
from aic_control_centre.execution.adapters import (
    INSPECT_MODULE,
    INSPECT_TARGET,
    build_adapter_registry,
)
from aic_control_centre.execution.inspect_project import (
    describe,
    inspect_directory,
)
from aic_control_centre.execution.process import ProcessAdapter
from aic_control_centre.execution.readonly import ReadOnlyAdapter
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _task(tmp_path):
    """Register a project with some files, a goal and a ready task."""
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "README.md").write_bytes(b"hello")
    (project / "src" / "app.py").write_bytes(b"x" * 3000)
    ProjectRegistry(tmp_path / "projects.json").add_project(project)
    goal = Goal.create(description="Look at it", project="project")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Inspect it")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    return task, project


def _grant(tmp_path):
    PermissionRegistry.beside(tmp_path / "tasks.json").grant(
        "project",
        INSPECT_TARGET,
        "look at the files",
    )


def _run(monkeypatch, tmp_path, task):
    return run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        INSPECT_TARGET,
    )


def _status(tmp_path, task):
    return TaskRegistry(tmp_path / "tasks.json").get_task(task.id).status


def test_the_shipped_registry_holds_inspect_and_noop() -> None:
    """These two are the only targets, and the names are sorted."""
    assert build_adapter_registry().list_targets() == ["inspect", "noop"]


def test_inspect_is_a_read_only_process_that_needs_a_grant() -> None:
    """The adapter is wrapped, runs the shipped module, and needs both."""
    adapter = build_adapter_registry().resolve(INSPECT_TARGET)

    assert isinstance(adapter, ReadOnlyAdapter)
    assert isinstance(adapter.adapter, ProcessAdapter)
    assert adapter.adapter.command == (
        sys.executable,
        "-m",
        INSPECT_MODULE,
    )
    assert adapter.requires_grant is True
    assert adapter.requires_project is True
    assert adapter.adapter.requires_project is True


def test_targets_lists_inspect_and_what_it_needs(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The listing says what it does and that it needs a grant."""
    assert run_cli(monkeypatch, tmp_path, "task", "targets") == 0

    output = capsys.readouterr().out

    assert "Execution targets: 2" in output
    assert (
        "inspect: reports what is in the project directory; "
        "changes nothing (needs a grant)"
    ) in output
    assert "noop: completes the task at once; no work is done" in output


def test_a_granted_run_completes_and_reports_the_project(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The reason is the description, and the history keeps it."""
    task, project = _task(tmp_path)
    _grant(tmp_path)
    reason = describe(inspect_directory(project))

    assert _run(monkeypatch, tmp_path, task) == 0

    output = capsys.readouterr().out

    assert "Result: completed" in output
    assert f"Reason: {reason}" in output
    assert reason == (
        "inspected project: 2 files, 1 directories, 2.9 KiB; "
        "largest: src/app.py (2.9 KiB), README.md (5 B); "
        "README: yes; .git: no"
    )
    assert _status(tmp_path, task) == "completed"

    assert run_cli(monkeypatch, tmp_path, "task", "history", task.id) == 0
    assert f"Reason: {reason}" in capsys.readouterr().out


def test_a_run_leaves_the_project_as_it_was(tmp_path, monkeypatch) -> None:
    """The project is the same after the run."""
    task, project = _task(tmp_path)
    _grant(tmp_path)
    before = describe(inspect_directory(project))

    assert _run(monkeypatch, tmp_path, task) == 0

    assert describe(inspect_directory(project)) == before
    assert sorted(path.name for path in project.iterdir()) == [
        "README.md",
        "src",
    ]


def test_a_run_without_a_grant_is_refused_and_writes_nothing(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The task stays ready and no attempt is recorded."""
    task, _ = _task(tmp_path)

    assert _run(monkeypatch, tmp_path, task) == 1

    output = capsys.readouterr().out

    assert "Result: rejected" in output
    assert "not granted" in output
    assert _status(tmp_path, task) == "ready"
    assert not (tmp_path / "executions.json").exists()


def test_a_run_is_refused_when_the_directory_is_gone(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Nothing runs and nothing is written for a deleted directory."""
    task, project = _task(tmp_path)
    _grant(tmp_path)
    shutil.rmtree(project)

    assert _run(monkeypatch, tmp_path, task) == 1

    output = capsys.readouterr().out

    assert "Result: rejected" in output
    assert "does not exist" in output
    assert _status(tmp_path, task) == "ready"
    assert not (tmp_path / "executions.json").exists()


def test_a_long_file_name_is_shown_cut(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The name is cut with dots, so the reason stays short."""
    task, project = _task(tmp_path)
    _grant(tmp_path)
    (project / ("n" * 70)).write_bytes(b"y" * 9000)

    assert _run(monkeypatch, tmp_path, task) == 0

    output = capsys.readouterr().out

    assert ("n" * 60 + "... (8.8 KiB)") in output
    assert "n" * 61 not in output
