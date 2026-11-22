"""Tests for the shipped git state adapter."""

import importlib.util
import os
import sys

from aic_control_centre.execution.adapters import (
    GITSTATE_DESCRIPTION,
    GITSTATE_MODULE,
    GITSTATE_TARGET,
    build_adapter_registry,
    build_gitstate_adapter,
)
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.git_state import describe, read_git_state
from aic_control_centre.execution.process import ProcessAdapter
from aic_control_centre.execution.readonly import ReadOnlyAdapter

COMMIT = "a1" * 20


def _project(tmp_path, repository=True):
    project = tmp_path / "project"
    project.mkdir()
    (project / "a.txt").write_bytes(b"text")

    if repository:
        git = project / ".git"
        (git / "refs" / "heads").mkdir(parents=True)
        (git / "hooks").mkdir()
        (git / "HEAD").write_bytes(b"ref: refs/heads/main\n")
        (git / "refs" / "heads" / "main").write_bytes(COMMIT.encode())

    return project


def _tree(root):
    return sorted(
        (path.relative_to(root).as_posix(), path.read_bytes())
        if path.is_file()
        else (path.relative_to(root).as_posix(), None)
        for path in root.rglob("*")
    )


def _execute(adapter, project):
    return adapter.execute(
        ExecutionRequest(
            task_id="task-1",
            target=GITSTATE_TARGET,
            project_path=project,
        ),
    )


def test_the_target_is_gitstate_and_the_module_exists() -> None:
    """The module that the adapter runs is the one that ships."""
    assert GITSTATE_TARGET == "gitstate"
    assert GITSTATE_MODULE == "aic_control_centre.execution.git_state"
    assert importlib.util.find_spec(GITSTATE_MODULE) is not None


def test_the_shipped_registry_holds_gitstate() -> None:
    """It is registered beside the others, and the names are sorted."""
    targets = build_adapter_registry().list_targets()

    assert "gitstate" in targets
    assert targets == sorted(targets)


def test_gitstate_is_a_read_only_process_that_needs_a_grant() -> None:
    """The adapter is wrapped, runs the shipped module, and needs both."""
    adapter = build_adapter_registry().resolve(GITSTATE_TARGET)

    assert isinstance(adapter, ReadOnlyAdapter)
    assert isinstance(adapter.adapter, ProcessAdapter)
    assert adapter.adapter.command == (
        sys.executable,
        "-B",
        "-m",
        GITSTATE_MODULE,
    )
    assert adapter.requires_grant is True
    assert adapter.adapter.requires_grant is True
    assert adapter.adapter.requires_project is True
    assert adapter.snapshots is True
    assert adapter.description == GITSTATE_DESCRIPTION
    assert GITSTATE_DESCRIPTION == (
        "reports the state of the git repository of the project by "
        "reading a few of its files; changes nothing"
    )


def test_a_run_on_a_repository_completes_with_its_state(tmp_path) -> None:
    """The reason is the description, and the task is the one asked."""
    project = _project(tmp_path)

    outcome = _execute(build_gitstate_adapter(), project)

    assert outcome.task_id == "task-1"
    assert outcome.outcome == "completed"
    assert outcome.reason == describe(read_git_state(project))
    assert outcome.reason.startswith(
        f"git state: branch main at {COMMIT[:12]}; 1 local branch; "
    )


def test_a_run_on_a_directory_without_a_repository_completes(
    tmp_path,
) -> None:
    """Nothing to read is an answer."""
    project = _project(tmp_path, repository=False)

    outcome = _execute(build_gitstate_adapter(), project)

    assert outcome.outcome == "completed"
    assert outcome.reason == "git state: not a git repository"


def test_a_run_on_a_reftable_repository_completes(tmp_path) -> None:
    """What is not read is said, and the outcome is not a failure."""
    project = _project(tmp_path)
    (project / ".git" / "reftable").mkdir()

    outcome = _execute(build_gitstate_adapter(), project)

    assert outcome.outcome == "completed"
    assert outcome.reason == (
        "git state not read: the refs are stored as reftable"
    )


def test_a_run_leaves_the_project_as_it_was_and_runs_no_hook(
    tmp_path,
) -> None:
    """No file changes, and a hook of the repository is not run."""
    project = _project(tmp_path)
    marker = tmp_path / "marker"
    hook = project / ".git" / "hooks" / "post-checkout"
    hook.write_bytes(f"#!/bin/sh\ntouch {marker}\n".encode())
    os.chmod(hook, 0o755)
    before = _tree(project)

    outcome = _execute(build_gitstate_adapter(), project)

    assert outcome.outcome == "completed"
    assert not marker.exists()
    assert _tree(project) == before
