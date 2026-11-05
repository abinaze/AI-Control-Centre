"""Tests for aic task run with the shipped pysyntax target."""

import shutil
import sys

from aic_control_centre.cli import main
from aic_control_centre.execution.adapters import (
    INSPECT_TARGET,
    PYSYNTAX_TARGET,
    build_adapter_registry,
)
from aic_control_centre.execution.check_python import (
    check_directory,
    describe,
    python_version,
)
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


def _task(tmp_path, files):
    """Register a project with these files, a goal and a ready task."""
    project = tmp_path / "project"
    project.mkdir()

    for name, text in files.items():
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    ProjectRegistry(tmp_path / "projects.json").add_project(project)
    goal = Goal.create(description="Check it", project="project")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Check the syntax")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    return task, project


def _grant(tmp_path, target=PYSYNTAX_TARGET):
    PermissionRegistry.beside(tmp_path / "tasks.json").grant(
        "project",
        target,
        "check the syntax",
    )


def _run(monkeypatch, tmp_path, task):
    return run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        PYSYNTAX_TARGET,
    )


def _status(tmp_path, task):
    return TaskRegistry(tmp_path / "tasks.json").get_task(task.id).status


def _listing(root):
    return sorted(
        (path.relative_to(root).as_posix(), path.is_file())
        for path in root.rglob("*")
    )


def test_targets_lists_pysyntax_and_what_it_needs(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The listing says what it does and that it needs a grant."""
    assert run_cli(monkeypatch, tmp_path, "task", "targets") == 0

    output = capsys.readouterr().out
    count = len(build_adapter_registry().list_targets())

    assert f"Execution targets: {count}" in output
    assert (
        "pysyntax: checks the syntax of the Python files in the project "
        "directory; changes nothing (needs a grant)"
    ) in output
    assert "inspect: reports what is in the project directory" in output


def test_a_granted_run_completes_and_reports_the_check(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The reason is the description, and the history keeps it."""
    task, project = _task(
        tmp_path,
        {"src/app.py": "x = 1\n", "README.md": "hello"},
    )
    _grant(tmp_path)
    reason = describe(check_directory(project))

    assert _run(monkeypatch, tmp_path, task) == 0

    output = capsys.readouterr().out

    assert "Result: completed" in output
    assert f"Reason: {reason}" in output
    assert reason == (
        f"checked Python syntax with Python {python_version()}: "
        "1 files checked, 0 with errors, 0 too large, 0 not read, "
        "0 directories skipped"
    )
    assert _status(tmp_path, task) == "completed"

    assert run_cli(monkeypatch, tmp_path, "task", "history", task.id) == 0
    assert f"Reason: {reason}" in capsys.readouterr().out


def test_a_granted_run_on_a_broken_project_fails_the_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The task fails, and the reason names the file and the line."""
    task, project = _task(
        tmp_path,
        {"src/app.py": "def f(:\n    pass\n", "ok.py": "x = 1\n"},
    )
    _grant(tmp_path)

    assert _run(monkeypatch, tmp_path, task) == 1

    output = capsys.readouterr().out

    assert "Result: failed" in output
    assert "1 with errors" in output
    assert "src/app.py line 1: " in output
    assert _status(tmp_path, task) == "failed"

    assert run_cli(monkeypatch, tmp_path, "task", "history", task.id) == 0
    assert "src/app.py line 1: " in capsys.readouterr().out


def test_a_virtual_environment_in_the_project_is_skipped(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Code that is not the project's own is not judged."""
    task, _ = _task(
        tmp_path,
        {
            "app.py": "x = 1\n",
            "env/pyvenv.cfg": "home = /usr\n",
            "env/lib/bad.py": "def f(:\n",
        },
    )
    _grant(tmp_path)

    assert _run(monkeypatch, tmp_path, task) == 0

    output = capsys.readouterr().out

    assert "1 files checked, 0 with errors" in output
    assert "1 directories skipped" in output


def test_a_run_leaves_the_project_as_it_was(tmp_path, monkeypatch) -> None:
    """The project is the same after the run, whatever it holds."""
    task, project = _task(
        tmp_path,
        {"a.py": "x = 1\n", "pkg/__init__.py": "", "pkg/b.py": "import a\n"},
    )
    _grant(tmp_path)
    before = _listing(project)

    assert _run(monkeypatch, tmp_path, task) == 0

    assert _listing(project) == before


def test_a_run_without_a_grant_is_refused_and_writes_nothing(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The task stays ready and no attempt is recorded."""
    task, _ = _task(tmp_path, {"a.py": "x = 1\n"})

    assert _run(monkeypatch, tmp_path, task) == 1

    output = capsys.readouterr().out

    assert "Result: rejected" in output
    assert "not granted" in output
    assert _status(tmp_path, task) == "ready"
    assert not (tmp_path / "executions.json").exists()


def test_a_grant_for_inspect_does_not_cover_pysyntax(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A grant is for one target, so each target is asked for on its own."""
    task, _ = _task(tmp_path, {"a.py": "x = 1\n"})
    _grant(tmp_path, INSPECT_TARGET)

    assert _run(monkeypatch, tmp_path, task) == 1

    output = capsys.readouterr().out

    assert "Result: rejected" in output
    assert "not granted" in output
    assert _status(tmp_path, task) == "ready"


def test_a_run_is_refused_when_the_directory_is_gone(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Nothing runs and nothing is written for a deleted directory."""
    task, project = _task(tmp_path, {"a.py": "x = 1\n"})
    _grant(tmp_path)
    shutil.rmtree(project)

    assert _run(monkeypatch, tmp_path, task) == 1

    output = capsys.readouterr().out

    assert "Result: rejected" in output
    assert "does not exist" in output
    assert _status(tmp_path, task) == "ready"
    assert not (tmp_path / "executions.json").exists()
