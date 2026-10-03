from pathlib import Path

import pytest

from aic_control_centre.projects.registry import ProjectRegistry


def test_empty_registry_returns_no_projects(tmp_path):
    registry = ProjectRegistry(tmp_path / "projects.json")

    assert registry.list_projects() == []


def test_add_project_persists_project(tmp_path):
    project_path = tmp_path / "example-project"
    project_path.mkdir()

    registry_path = tmp_path / "projects.json"
    registry = ProjectRegistry(registry_path)

    project = registry.add_project(project_path)

    assert project.name == "example-project"
    assert project.path == project_path.resolve()

    saved_registry = ProjectRegistry(registry_path)

    assert saved_registry.list_projects() == [project]


def test_add_project_does_not_duplicate_existing_project(tmp_path):
    project_path = tmp_path / "example-project"
    project_path.mkdir()

    registry = ProjectRegistry(tmp_path / "projects.json")

    first = registry.add_project(project_path)
    second = registry.add_project(project_path)

    assert first == second
    assert registry.list_projects() == [first]


def test_add_project_rejects_missing_path(tmp_path):
    registry = ProjectRegistry(tmp_path / "projects.json")

    missing_path = tmp_path / "missing-project"

    try:
        registry.add_project(missing_path)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Expected FileNotFoundError")


def test_add_project_rejects_file_path(tmp_path):
    file_path = tmp_path / "project.txt"
    file_path.write_text("test", encoding="utf-8")

    registry = ProjectRegistry(tmp_path / "projects.json")

    try:
        registry.add_project(file_path)
    except NotADirectoryError:
        pass
    else:
        raise AssertionError("Expected NotADirectoryError")


def _fail_replace(*args, **kwargs):
    raise OSError("simulated crash")


def test_failed_save_keeps_existing_registry_file(tmp_path, monkeypatch):
    first_path = tmp_path / "first-project"
    first_path.mkdir()
    second_path = tmp_path / "second-project"
    second_path.mkdir()

    registry_path = tmp_path / "projects.json"
    registry = ProjectRegistry(registry_path)
    first = registry.add_project(first_path)
    before = registry_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        "aic_control_centre.storage.os.replace",
        _fail_replace,
    )

    with pytest.raises(OSError, match="simulated crash"):
        registry.add_project(second_path)

    assert registry_path.read_text(encoding="utf-8") == before
    assert ProjectRegistry(registry_path).list_projects() == [first]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "first-project",
        "projects.json",
        "second-project",
    ]
