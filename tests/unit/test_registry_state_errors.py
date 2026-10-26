"""Tests for how the registries treat a state file that cannot be read."""

import pathlib

import pytest

from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.storage import StateFileError
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


def _seed_projects(registry, tmp_path):
    (tmp_path / "alpha").mkdir()
    registry.add_project(tmp_path / "alpha")


def _seed_goals(registry, tmp_path):
    registry.add_goal(Goal.create(description="A goal", project="alpha"))


def _seed_tasks(registry, tmp_path):
    registry.add_task(Task.create(goal_id="goal-1", title="A task"))


def _seed_permissions(registry, tmp_path):
    registry.grant("alpha", "inspect", "for a test")


def _seed_records(registry, tmp_path):
    registry.open_attempt("task-1", "cli", "noop")


REGISTRIES = {
    "projects": (ProjectRegistry, "list_projects", _seed_projects),
    "goals": (GoalRegistry, "list_goals", _seed_goals),
    "tasks": (TaskRegistry, "list_tasks", _seed_tasks),
    "permissions": (PermissionRegistry, "list_grants", _seed_permissions),
    "records": (ExecutionRecordRegistry, "list_records", _seed_records),
}


def _fail_reads(monkeypatch, path):
    """Make reading one file fail with an access error."""
    real = pathlib.Path.read_text

    def read_text(self, *arguments, **options):
        if self == path:
            raise PermissionError(13, "Access is denied")

        return real(self, *arguments, **options)

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)


def _hide_from_pathlib(monkeypatch, path):
    """Make Path.exists answer no for one path, as pathlib does on error."""
    real = pathlib.Path.exists

    def exists(self, **options):
        return False if self == path else real(self, **options)

    monkeypatch.setattr(pathlib.Path, "exists", exists)


@pytest.mark.parametrize("name", sorted(REGISTRIES))
def test_a_missing_file_is_an_empty_registry(tmp_path, name) -> None:
    """Nothing saved yet is not an error."""
    factory, listing, _ = REGISTRIES[name]

    registry = factory(tmp_path / "state.json")

    assert getattr(registry, listing)() == []


@pytest.mark.parametrize("name", sorted(REGISTRIES))
def test_an_unreadable_file_is_an_error_and_not_an_empty_registry(
    tmp_path,
    monkeypatch,
    name,
) -> None:
    """The registry says that it cannot read, and does not say it is empty."""
    factory, listing, seed = REGISTRIES[name]
    path = tmp_path / "state.json"
    registry = factory(path)
    seed(registry, tmp_path)
    _fail_reads(monkeypatch, path)

    with pytest.raises(StateFileError, match="cannot be read"):
        getattr(registry, listing)()


@pytest.mark.parametrize("name", sorted(REGISTRIES))
def test_a_file_that_pathlib_calls_missing_is_still_read(
    tmp_path,
    monkeypatch,
    name,
) -> None:
    """Items that were saved are not lost to an answer from Path.exists()."""
    factory, listing, seed = REGISTRIES[name]
    path = tmp_path / "state.json"
    registry = factory(path)
    seed(registry, tmp_path)
    _hide_from_pathlib(monkeypatch, path)

    assert len(getattr(registry, listing)()) == 1


def _add_projects(registry, tmp_path):
    (tmp_path / "beta").mkdir()
    registry.add_project(tmp_path / "beta")


def _add_goals(registry, tmp_path):
    registry.add_goal(Goal.create(description="Another", project="alpha"))


def _add_tasks(registry, tmp_path):
    registry.add_task(Task.create(goal_id="goal-1", title="Another"))


def _add_permissions(registry, tmp_path):
    registry.grant("alpha", "other", "for a test")


def _add_records(registry, tmp_path):
    registry.open_attempt("task-2", "cli", "noop")


ADDERS = {
    "projects": _add_projects,
    "goals": _add_goals,
    "tasks": _add_tasks,
    "permissions": _add_permissions,
    "records": _add_records,
}


@pytest.mark.parametrize("name", sorted(REGISTRIES))
def test_adding_while_pathlib_hides_the_file_keeps_what_was_saved(
    tmp_path,
    monkeypatch,
    name,
) -> None:
    """The next save must not overwrite the file with only the new item."""
    factory, listing, seed = REGISTRIES[name]
    path = tmp_path / "state.json"
    registry = factory(path)
    seed(registry, tmp_path)
    _hide_from_pathlib(monkeypatch, path)

    ADDERS[name](registry, tmp_path)
    monkeypatch.undo()

    assert len(getattr(registry, listing)()) == 2


def _refused_without_a_write(monkeypatch, path, action):
    """Run an action that must fail, and show the file was not touched."""
    before = path.read_bytes()
    _fail_reads(monkeypatch, path)

    with pytest.raises(StateFileError, match="cannot be read"):
        action()

    monkeypatch.undo()

    assert path.read_bytes() == before


def test_a_project_is_not_saved_over_a_file_that_cannot_be_read(
    tmp_path,
    monkeypatch,
) -> None:
    """The registry that could not be read keeps what it had."""
    path = tmp_path / "projects.json"
    registry = ProjectRegistry(path)
    _seed_projects(registry, tmp_path)
    (tmp_path / "beta").mkdir()

    _refused_without_a_write(
        monkeypatch,
        path,
        lambda: registry.add_project(tmp_path / "beta"),
    )

    assert [project.name for project in registry.list_projects()] == [
        "alpha",
    ]


def test_a_goal_is_not_saved_over_a_file_that_cannot_be_read(
    tmp_path,
    monkeypatch,
) -> None:
    """The same rule holds for goals."""
    path = tmp_path / "goals.json"
    registry = GoalRegistry(path)
    _seed_goals(registry, tmp_path)

    _refused_without_a_write(
        monkeypatch,
        path,
        lambda: registry.add_goal(
            Goal.create(description="Another", project="alpha"),
        ),
    )

    assert len(registry.list_goals()) == 1


def test_a_task_is_not_saved_over_a_file_that_cannot_be_read(
    tmp_path,
    monkeypatch,
) -> None:
    """The same rule holds for tasks."""
    path = tmp_path / "tasks.json"
    registry = TaskRegistry(path)
    _seed_tasks(registry, tmp_path)

    _refused_without_a_write(
        monkeypatch,
        path,
        lambda: registry.add_task(
            Task.create(goal_id="goal-1", title="Another"),
        ),
    )

    assert len(registry.list_tasks()) == 1


def test_a_grant_is_not_saved_over_a_file_that_cannot_be_read(
    tmp_path,
    monkeypatch,
) -> None:
    """A grant that was given is not lost when the file cannot be read."""
    path = tmp_path / "permissions.json"
    registry = PermissionRegistry(path)
    _seed_permissions(registry, tmp_path)

    _refused_without_a_write(
        monkeypatch,
        path,
        lambda: registry.grant("alpha", "other", "for a test"),
    )

    assert registry.is_granted("alpha", "inspect") is True


def test_an_attempt_is_not_saved_over_a_file_that_cannot_be_read(
    tmp_path,
    monkeypatch,
) -> None:
    """The same rule holds for execution records."""
    path = tmp_path / "executions.json"
    registry = ExecutionRecordRegistry(path)
    _seed_records(registry, tmp_path)

    _refused_without_a_write(
        monkeypatch,
        path,
        lambda: registry.open_attempt("task-2", "cli", "noop"),
    )

    assert len(registry.list_records()) == 1
