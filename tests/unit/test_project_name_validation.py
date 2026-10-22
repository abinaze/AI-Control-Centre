"""Tests for duplicate project names in validation."""

import sys

from aic_control_centre.cli import main
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.validation.goal_tasks import GoalTaskValidator


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _write_projects(tmp_path, paths):
    """Write projects directly, bypassing the registry's own rule."""
    write_text_atomic(
        tmp_path / "projects.json",
        serialize_state_items(
            "projects",
            [{"name": path.name, "path": str(path)} for path in paths],
        ),
    )


def _directories(tmp_path, *parents, name="app"):
    paths = []

    for parent in parents:
        path = tmp_path / parent / name
        path.mkdir(parents=True)
        paths.append(path)

    return paths


def _validator(tmp_path, check_projects=True):
    return GoalTaskValidator(
        goal_registry=GoalRegistry(tmp_path / "goals.json"),
        task_registry=TaskRegistry(tmp_path / "tasks.json"),
        project_registry=(
            ProjectRegistry(tmp_path / "projects.json")
            if check_projects
            else None
        ),
    )


def test_unique_project_names_are_valid(tmp_path) -> None:
    """Different names are not a problem."""
    first, = _directories(tmp_path, "one", name="app")
    second, = _directories(tmp_path, "two", name="tool")
    _write_projects(tmp_path, [first, second])

    assert _validator(tmp_path).validate().valid is True


def test_a_name_used_by_two_directories_is_reported(tmp_path) -> None:
    """Both directories are named, in the order they were registered."""
    first, second = _directories(tmp_path, "one", "two")
    _write_projects(tmp_path, [first, second])

    result = _validator(tmp_path).validate()

    assert result.errors == (
        "Project name is used by more than one directory: "
        f"app ({first}, {second})",
    )


def test_a_name_used_by_three_directories_is_reported_once(tmp_path) -> None:
    """One line per name, however many directories share it."""
    paths = _directories(tmp_path, "one", "two", "three")
    _write_projects(tmp_path, paths)

    result = _validator(tmp_path).validate()

    assert len(result.errors) == 1
    assert all(str(path) in result.errors[0] for path in paths)


def test_every_shared_name_is_reported(tmp_path) -> None:
    """Two different clashes give two lines."""
    apps = _directories(tmp_path, "one", "two", name="app")
    tools = _directories(tmp_path, "three", "four", name="tool")
    _write_projects(tmp_path, [*apps, *tools])

    result = _validator(tmp_path).validate()

    assert len(result.errors) == 2


def test_project_names_are_not_checked_without_a_project_registry(
    tmp_path,
) -> None:
    """The check follows the other project checks and is opt-in."""
    first, second = _directories(tmp_path, "one", "two")
    _write_projects(tmp_path, [first, second])

    assert _validator(tmp_path, check_projects=False).validate().valid is True


def test_validation_does_not_modify_the_projects_file(tmp_path) -> None:
    """Reporting a clash is not repairing it."""
    first, second = _directories(tmp_path, "one", "two")
    _write_projects(tmp_path, [first, second])
    before = (tmp_path / "projects.json").read_bytes()

    _validator(tmp_path).validate()

    assert (tmp_path / "projects.json").read_bytes() == before


def test_aic_validate_fails_on_a_shared_project_name(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The reproduced case: two directories called app no longer pass."""
    first, second = _directories(tmp_path, "one", "two")
    data = tmp_path / "data"
    data.mkdir()
    _write_projects(data, [first, second])

    result = run_cli(monkeypatch, data, "validate")

    output = capsys.readouterr().out

    assert result == 1
    assert "Project name is used by more than one directory: app" in output
    assert "Validation passed." not in output


def test_aic_validate_passes_for_projects_added_through_the_cli(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The command's own rule keeps a clean state clean."""
    first, = _directories(tmp_path, "one", name="app")
    second, = _directories(tmp_path, "two", name="tool")
    data = tmp_path / "data"

    for path in (first, second):
        assert run_cli(monkeypatch, data, "project", "add", str(path)) == 0

    capsys.readouterr()

    assert run_cli(monkeypatch, data, "validate") == 0
    assert "Validation passed." in capsys.readouterr().out
