"""Tests for project directories in validation."""

import shutil
import sys

from aic_control_centre.cli import main
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import Project, ProjectRegistry
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.validation.goal_tasks import GoalTaskValidator


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


class UnreadablePath:
    """A path whose directory cannot be looked at."""

    def __str__(self):
        return "/unreadable"

    def exists(self):
        raise PermissionError("denied")

    def is_dir(self):
        raise PermissionError("denied")


class StubProjects:
    """A project registry with one project that cannot be looked at."""

    def list_projects(self):
        return [Project(name="app", path=UnreadablePath())]


def _register(tmp_path, name="app"):
    path = tmp_path / name
    path.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(path)

    return path.resolve()


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


def test_a_project_with_a_directory_is_valid(tmp_path) -> None:
    """A registered directory that exists is not reported."""
    _register(tmp_path)

    assert _validator(tmp_path).validate().valid is True


def test_a_project_whose_directory_is_gone_is_reported(tmp_path) -> None:
    """The report names the project and the path."""
    path = _register(tmp_path)
    shutil.rmtree(path)

    result = _validator(tmp_path).validate()

    assert result.valid is False
    assert result.errors == (
        f"Project directory does not exist: app ({path})",
    )


def test_a_project_whose_path_is_a_file_is_reported(tmp_path) -> None:
    """A file where the directory was is reported as such."""
    path = _register(tmp_path)
    shutil.rmtree(path)
    path.write_text("a file now", encoding="utf-8")

    result = _validator(tmp_path).validate()

    assert result.errors == (
        f"Project path is not a directory: app ({path})",
    )


def test_every_missing_directory_is_reported(tmp_path) -> None:
    """One line for each project, in the order they were registered."""
    first = _register(tmp_path, "first")
    _register(tmp_path, "second")
    third = _register(tmp_path, "third")
    shutil.rmtree(first)
    shutil.rmtree(third)

    result = _validator(tmp_path).validate()

    assert result.errors == (
        f"Project directory does not exist: first ({first})",
        f"Project directory does not exist: third ({third})",
    )


def test_directories_are_not_checked_without_a_project_registry(
    tmp_path,
) -> None:
    """The check is opt-in, like the other project checks."""
    path = _register(tmp_path)
    shutil.rmtree(path)

    result = _validator(tmp_path, check_projects=False).validate()

    assert result.valid is True


def test_validation_does_not_create_the_missing_directory(tmp_path) -> None:
    """Validation only looks. It writes nothing and creates nothing."""
    path = _register(tmp_path)
    shutil.rmtree(path)
    before = (tmp_path / "projects.json").read_bytes()

    _validator(tmp_path).validate()

    assert not path.exists()
    assert (tmp_path / "projects.json").read_bytes() == before


def test_a_directory_that_cannot_be_read_is_reported(tmp_path) -> None:
    """An error from the file system is a line in the report, not a crash."""
    validator = GoalTaskValidator(
        goal_registry=GoalRegistry(tmp_path / "goals.json"),
        task_registry=TaskRegistry(tmp_path / "tasks.json"),
        project_registry=StubProjects(),
    )

    result = validator.validate()

    assert result.errors == (
        "Project directory cannot be read: app (/unreadable)",
    )


def test_aic_validate_fails_on_a_missing_project_directory(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The command reports the directory and exits 1."""
    path = _register(tmp_path)
    shutil.rmtree(path)

    result = run_cli(monkeypatch, tmp_path, "validate")

    output = capsys.readouterr().out

    assert result == 1
    assert "Validation failed." in output
    assert f"Project directory does not exist: app ({path})" in output


def test_aic_validate_passes_when_the_directory_is_back(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Putting the directory back is the repair."""
    path = _register(tmp_path)
    shutil.rmtree(path)

    assert run_cli(monkeypatch, tmp_path, "validate") == 1

    path.mkdir()
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "validate") == 0
    assert "Validation passed." in capsys.readouterr().out
