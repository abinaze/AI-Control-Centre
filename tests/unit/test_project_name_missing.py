"""Tests for refusing a project directory that has no name."""

import sys
from pathlib import Path

import pytest

from aic_control_centre.cli import main
from aic_control_centre.projects.registry import ProjectRegistry


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _root(tmp_path):
    """The root of the drive or the file system that holds tmp_path."""
    return Path(tmp_path.anchor)


def test_the_root_of_a_drive_is_refused(tmp_path) -> None:
    """It has no name, and the name is what identifies a project."""
    from aic_control_centre.projects.registry import ProjectNameMissingError

    registry = ProjectRegistry(tmp_path / "projects.json")

    with pytest.raises(ProjectNameMissingError) as raised:
        registry.add_project(_root(tmp_path))

    assert raised.value.path == _root(tmp_path).resolve()
    assert "has no name of its own" in str(raised.value)
    assert str(_root(tmp_path).resolve()) in str(raised.value)


def test_it_is_a_value_error_like_the_other_refusals(tmp_path) -> None:
    """A caller that catches ValueError for names still catches it."""
    registry = ProjectRegistry(tmp_path / "projects.json")

    with pytest.raises(ValueError):
        registry.add_project(_root(tmp_path))


def test_the_root_is_refused_however_it_is_written(tmp_path) -> None:
    """A path that resolves to the root has no name either."""
    registry = ProjectRegistry(tmp_path / "projects.json")

    with pytest.raises(ValueError):
        registry.add_project(_root(tmp_path) / ".")

    assert registry.list_projects() == []


def test_a_refused_root_writes_nothing(tmp_path) -> None:
    """Nothing is saved, and a registry that exists is not changed."""
    project = tmp_path / "app"
    project.mkdir()
    registry = ProjectRegistry(tmp_path / "projects.json")

    with pytest.raises(ValueError):
        registry.add_project(_root(tmp_path))

    assert not (tmp_path / "projects.json").exists()

    registry.add_project(project)
    before = (tmp_path / "projects.json").read_bytes()

    with pytest.raises(ValueError):
        registry.add_project(_root(tmp_path))

    assert (tmp_path / "projects.json").read_bytes() == before


def test_a_missing_directory_is_still_reported_as_missing(tmp_path) -> None:
    """The order of the checks is the same as before: it must exist first."""
    registry = ProjectRegistry(tmp_path / "projects.json")
    missing = _root(tmp_path) / "aic-no-such-folder-for-the-test"

    with pytest.raises(FileNotFoundError):
        registry.add_project(missing)


def test_the_command_says_why_and_registers_nothing(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Two lines, exit status 1, and an empty registry."""
    root = _root(tmp_path).resolve()

    assert run_cli(monkeypatch, tmp_path, "project", "add", str(root)) == 1

    lines = capsys.readouterr().out.splitlines()

    assert lines == [
        f"Error: the directory {root} has no name of its own, as the "
        "root of a drive has none, so it cannot be a project",
        "Register a directory below it.",
    ]
    assert not (tmp_path / "projects.json").exists()

    assert run_cli(monkeypatch, tmp_path, "project", "list") == 0
    assert "No projects registered." in capsys.readouterr().out


def test_a_directory_with_a_name_is_still_registered(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The refusal is only for a directory that has no name."""
    project = tmp_path / "app"
    project.mkdir()
    root = _root(tmp_path)

    assert run_cli(monkeypatch, tmp_path, "project", "add", str(root)) == 1
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "add", str(project)) == 0

    lines = capsys.readouterr().out.splitlines()

    assert lines[0] == "Project registered: app"


def test_a_dot_is_the_directory_it_stands_for(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The name comes from the resolved path and not from the argument."""
    project = tmp_path / "app"
    project.mkdir()
    monkeypatch.chdir(project)

    assert run_cli(monkeypatch, tmp_path, "project", "add", ".") == 0
    assert capsys.readouterr().out.splitlines()[0] == (
        "Project registered: app"
    )
