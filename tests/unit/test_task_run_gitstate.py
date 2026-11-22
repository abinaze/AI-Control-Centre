"""Tests for aic task run with the shipped gitstate target."""

import sys

from aic_control_centre.cli import main
from aic_control_centre.execution import snapshot as snapshot_module
from aic_control_centre.execution.adapters import (
    GITSTATE_TARGET,
    PYSYNTAX_TARGET,
    build_adapter_registry,
)
from aic_control_centre.execution.git_state import describe, read_git_state
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry

COMMIT = "a1" * 20


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _task(tmp_path, repository=True):
    """Register a project, with a git repository or not, and a task."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_bytes(b"hello")

    if repository:
        git = project / ".git"
        (git / "refs" / "heads").mkdir(parents=True)
        (git / "logs").mkdir()
        (git / "HEAD").write_bytes(b"ref: refs/heads/main\n")
        (git / "refs" / "heads" / "main").write_bytes(COMMIT.encode() + b"\n")
        (git / "logs" / "HEAD").write_bytes(
            f"{COMMIT} {COMMIT} A <a@b.c> 1700000000 +0000\tc\n".encode()
        )

    ProjectRegistry(tmp_path / "projects.json").add_project(project)
    goal = Goal.create(description="Look at git", project="project")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Look at the repository")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    return task, project


def _grant(tmp_path, target=GITSTATE_TARGET):
    PermissionRegistry.beside(tmp_path / "tasks.json").grant(
        "project",
        target,
        "look at the git state",
    )


def _run(monkeypatch, tmp_path, task):
    return run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        GITSTATE_TARGET,
    )


def _status(tmp_path, task):
    return TaskRegistry(tmp_path / "tasks.json").get_task(task.id).status


def test_targets_lists_gitstate_and_what_it_needs(
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
        "gitstate: reports the state of the git repository of the project "
        "by reading a few of its files; changes nothing (needs a grant)"
    ) in output


def test_a_granted_run_reports_the_git_state(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The four lines are exact, and the history keeps the reason."""
    task, project = _task(tmp_path)
    _grant(tmp_path)
    reason = describe(read_git_state(project))
    capsys.readouterr()

    assert _run(monkeypatch, tmp_path, task) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"Task: {task.id}",
        f"Target: {GITSTATE_TARGET}",
        "Result: completed",
        f"Reason: {reason}",
    ]
    assert reason == (
        f"git state: branch main at {COMMIT[:12]}; 1 local branch; "
        "stash: no; operation in progress: none; index.lock: no; "
        "last HEAD change: 2023-11-14T22:13:20Z"
    )
    assert _status(tmp_path, task) == "completed"

    assert run_cli(monkeypatch, tmp_path, "task", "history", task.id) == 0
    assert f"Reason: {reason}" in capsys.readouterr().out


def test_a_project_with_no_repository_completes_the_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """No repository is an answer, and it does not fail the goal."""
    task, _ = _task(tmp_path, repository=False)
    _grant(tmp_path)
    capsys.readouterr()

    assert _run(monkeypatch, tmp_path, task) == 0

    output = capsys.readouterr().out

    assert "Result: completed" in output
    assert "Reason: git state: not a git repository" in output
    assert _status(tmp_path, task) == "completed"


def test_a_run_without_a_grant_is_refused_and_writes_nothing(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A grant for another target does not cover this one."""
    task, _ = _task(tmp_path)
    _grant(tmp_path, PYSYNTAX_TARGET)
    capsys.readouterr()

    assert _run(monkeypatch, tmp_path, task) == 1

    assert capsys.readouterr().out.splitlines() == [
        f"Task: {task.id}",
        f"Target: {GITSTATE_TARGET}",
        "Result: rejected",
        "Reason: target gitstate is not granted for project project",
    ]
    assert _status(tmp_path, task) == "ready"
    assert not (tmp_path / "executions.json").exists()


def test_a_project_over_the_snapshot_limit_is_refused(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The git directory counts, and the task stays ready."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 2)
    task, _ = _task(tmp_path)
    _grant(tmp_path)
    capsys.readouterr()

    assert _run(monkeypatch, tmp_path, task) == 1

    output = capsys.readouterr().out

    assert "Result: rejected" in output
    assert "project project has more than 2 files" in output
    assert _status(tmp_path, task) == "ready"
    assert not (tmp_path / "executions.json").exists()
