"""Tests for finding and removing a registered project."""

import pytest

from aic_control_centre.projects import registry as registry_module
from aic_control_centre.projects.registry import (
    Project,
    ProjectNameAmbiguousError,
    ProjectNotRegisteredError,
    ProjectRegistry,
)
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)


def _write(tmp_path, *entries):
    """Write projects directly, as a file edited by hand could hold them."""
    write_text_atomic(
        tmp_path / "projects.json",
        serialize_state_items(
            "projects",
            [{"name": name, "path": str(path)} for name, path in entries],
        ),
    )

    return ProjectRegistry(tmp_path / "projects.json")


def test_a_project_is_found_by_its_name(tmp_path) -> None:
    """The project that has the name is returned."""
    registry = _write(
        tmp_path,
        ("app", tmp_path / "one" / "app"),
        ("lib", tmp_path / "one" / "lib"),
    )

    assert registry.find_project("lib") == Project(
        name="lib",
        path=tmp_path / "one" / "lib",
    )


def test_an_unknown_name_is_not_registered(tmp_path) -> None:
    """The error names the project, and nothing is written."""
    registry = ProjectRegistry(tmp_path / "projects.json")

    with pytest.raises(ProjectNotRegisteredError) as caught:
        registry.find_project("app")

    assert str(caught.value) == "no project named app is registered"
    assert not (tmp_path / "projects.json").exists()


def test_the_name_is_matched_exactly(tmp_path) -> None:
    """A name that differs in case is another name."""
    registry = _write(tmp_path, ("app", tmp_path / "app"))

    with pytest.raises(ProjectNotRegisteredError):
        registry.find_project("App")


def test_a_shared_name_needs_the_directory(tmp_path) -> None:
    """Both directories are in the error."""
    first = tmp_path / "one" / "app"
    second = tmp_path / "two" / "app"
    registry = _write(tmp_path, ("app", first), ("app", second))

    with pytest.raises(ProjectNameAmbiguousError) as caught:
        registry.find_project("app")

    assert caught.value.paths == [first, second]
    assert str(caught.value) == (
        f"2 projects are named app: {first}, {second}"
    )


def test_the_directory_picks_one_of_a_shared_name(tmp_path) -> None:
    """The path may be spelled with a parent step."""
    first = tmp_path / "one" / "app"
    second = tmp_path / "two" / "app"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    registry = _write(tmp_path, ("app", first), ("app", second))

    assert registry.find_project("app", second).path == second
    assert registry.find_project("app", first).path == first
    assert registry.find_project(
        "app",
        tmp_path / "two" / ".." / "two" / "app",
    ).path == second


def test_a_directory_that_is_gone_can_still_be_picked(tmp_path) -> None:
    """The directory of a project may be the very thing that is missing."""
    gone = tmp_path / "gone" / "app"
    registry = _write(tmp_path, ("app", gone), ("app", tmp_path / "x"))

    assert registry.find_project("app", gone).path == gone


def test_a_directory_that_matches_nothing_is_not_registered(
    tmp_path,
) -> None:
    """The error says which directory was asked for."""
    registry = _write(tmp_path, ("app", tmp_path / "one" / "app"))
    other = tmp_path / "other" / "app"

    with pytest.raises(ProjectNotRegisteredError) as caught:
        registry.find_project("app", other)

    assert str(caught.value) == (
        f"no project named app is registered at {other}"
    )


def test_the_same_entry_twice_needs_the_directory(tmp_path) -> None:
    """Without a directory it is a shared name, and with one it is not."""
    path = tmp_path / "app"
    registry = _write(tmp_path, ("app", path), ("app", path))

    with pytest.raises(ProjectNameAmbiguousError):
        registry.find_project("app")

    assert registry.find_project("app", path).path == path


def test_removing_a_project_keeps_the_others_in_order(tmp_path) -> None:
    """Only the entry that was asked for goes."""
    paths = [tmp_path / name for name in ("a", "b", "c", "d")]
    registry = _write(tmp_path, *[(path.name, path) for path in paths])

    registry.remove_project(registry.find_project("b"))

    saved = ProjectRegistry(registry.registry_path).list_projects()

    assert [project.name for project in registry.list_projects()] == [
        "a",
        "c",
        "d",
    ]
    assert [project.name for project in saved] == ["a", "c", "d"]


def test_removing_one_of_two_equal_entries_removes_one(tmp_path) -> None:
    """The file held the entry twice, and now holds it once."""
    path = tmp_path / "app"
    registry = _write(tmp_path, ("app", path), ("app", path))

    registry.remove_project(registry.find_project("app", path))

    assert registry.list_projects() == [Project(name="app", path=path)]


def test_removing_never_touches_the_directory(tmp_path) -> None:
    """The registry entry goes and the files stay."""
    directory = tmp_path / "app"
    directory.mkdir()
    (directory / "keep.txt").write_bytes(b"keep")
    registry = ProjectRegistry(tmp_path / "projects.json")
    project = registry.add_project(directory)

    registry.remove_project(project)

    assert registry.list_projects() == []
    assert (directory / "keep.txt").read_bytes() == b"keep"


def test_removing_a_project_that_is_not_registered_changes_nothing(
    tmp_path,
) -> None:
    """The error is raised and the file is the same afterwards."""
    registry = _write(tmp_path, ("app", tmp_path / "app"))
    before = registry.registry_path.read_bytes()

    with pytest.raises(ProjectNotRegisteredError):
        registry.remove_project(
            Project(name="app", path=tmp_path / "elsewhere"),
        )

    assert registry.registry_path.read_bytes() == before


def test_a_failed_write_leaves_the_registry_as_it_was(
    tmp_path,
    monkeypatch,
) -> None:
    """The entry is still there when the file cannot be written."""
    registry = _write(tmp_path, ("app", tmp_path / "app"))
    before = registry.registry_path.read_bytes()
    project = registry.find_project("app")

    def refuse(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(registry_module, "write_text_atomic", refuse)

    with pytest.raises(OSError):
        registry.remove_project(project)

    monkeypatch.undo()

    assert registry.registry_path.read_bytes() == before
    assert registry.list_projects() == [project]
