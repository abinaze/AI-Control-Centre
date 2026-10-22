"""Tests for unique project names."""

import sys

import pytest

from aic_control_centre.cli import main
from aic_control_centre.projects.commands import add_project
from aic_control_centre.projects.registry import (
    ProjectNameInUseError,
    ProjectRegistry,
)
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)


def _directories(tmp_path, *parents, name="app"):
    """Make a directory called name inside each of several parents."""
    paths = []

    for parent in parents:
        path = tmp_path / parent / name
        path.mkdir(parents=True)
        paths.append(path)

    return paths


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def test_a_second_directory_with_the_same_name_is_refused(tmp_path) -> None:
    """The name identifies a project, so two directories cannot share it."""
    first, second = _directories(tmp_path, "one", "two")
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add_project(first)

    with pytest.raises(ProjectNameInUseError):
        registry.add_project(second)


def test_the_error_names_the_directory_that_holds_the_name(tmp_path) -> None:
    """A person can see which directory is in the way."""
    first, second = _directories(tmp_path, "one", "two")
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add_project(first)

    with pytest.raises(ProjectNameInUseError) as raised:
        registry.add_project(second)

    assert raised.value.name == "app"
    assert raised.value.existing_path == first.resolve()
    assert str(first.resolve()) in str(raised.value)
    assert "app" in str(raised.value)


def test_a_refused_project_changes_nothing(tmp_path) -> None:
    """The registry file is identical afterwards."""
    first, second = _directories(tmp_path, "one", "two")
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add_project(first)
    before = (tmp_path / "projects.json").read_bytes()

    with pytest.raises(ProjectNameInUseError):
        registry.add_project(second)

    assert (tmp_path / "projects.json").read_bytes() == before
    assert [project.path for project in registry.list_projects()] == [
        first.resolve(),
    ]


def test_directories_with_different_names_can_both_be_registered(
    tmp_path,
) -> None:
    """Only a shared name is a problem."""
    first, = _directories(tmp_path, "one", name="app")
    second, = _directories(tmp_path, "two", name="tool")
    registry = ProjectRegistry(tmp_path / "projects.json")

    registry.add_project(first)
    registry.add_project(second)

    assert [project.name for project in registry.list_projects()] == [
        "app",
        "tool",
    ]


def test_the_same_directory_is_still_registered_once(tmp_path) -> None:
    """Registering a directory again, however it is spelled, is not a clash."""
    first, = _directories(tmp_path, "one")
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add_project(first)

    again = registry.add_project(first / ".." / "app")

    assert again.path == first.resolve()
    assert len(registry.list_projects()) == 1


def test_names_are_compared_exactly(tmp_path) -> None:
    """Capital letters make a different name, as in a lookup by name."""
    first, = _directories(tmp_path, "one", name="App")
    second, = _directories(tmp_path, "two", name="app")
    registry = ProjectRegistry(tmp_path / "projects.json")

    registry.add_project(first)
    registry.add_project(second)

    assert len(registry.list_projects()) == 2


def test_a_state_that_already_has_duplicates_can_still_be_read(
    tmp_path,
) -> None:
    """Existing data is listed, and a third directory is still refused."""
    first, second, third = _directories(tmp_path, "one", "two", "three")
    write_text_atomic(
        tmp_path / "projects.json",
        serialize_state_items(
            "projects",
            [
                {"name": "app", "path": str(first)},
                {"name": "app", "path": str(second)},
            ],
        ),
    )
    registry = ProjectRegistry(tmp_path / "projects.json")

    assert len(registry.list_projects()) == 2

    with pytest.raises(ProjectNameInUseError) as raised:
        registry.add_project(third)

    assert raised.value.existing_path == first


def test_the_command_reports_the_clash_and_says_how_to_go_on(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The message names the directory and suggests a way out."""
    first, second = _directories(tmp_path, "one", "two")
    monkeypatch.setenv("AIC_DATA_DIR", str(tmp_path / "data"))

    assert add_project(str(first)) == 0
    capsys.readouterr()

    assert add_project(str(second)) == 1

    output = capsys.readouterr().out

    assert (
        f"Error: a project named app is already registered at "
        f"{first.resolve()}"
    ) in output
    assert "must be unique" in output
    assert "Rename one of the directories" in output
    assert "Project registered" not in output


def test_the_cli_refuses_the_second_project(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Through aic project add, the second add exits 1 and changes nothing."""
    first, second = _directories(tmp_path, "one", "two")
    data = tmp_path / "data"

    assert run_cli(monkeypatch, data, "project", "add", str(first)) == 0
    before = (data / "projects.json").read_bytes()
    capsys.readouterr()

    assert run_cli(monkeypatch, data, "project", "add", str(second)) == 1

    assert "already registered" in capsys.readouterr().out
    assert (data / "projects.json").read_bytes() == before
