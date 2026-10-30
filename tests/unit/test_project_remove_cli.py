"""Tests for aic project remove."""

import sys

from aic_control_centre.cli import main
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _register(monkeypatch, tmp_path, name="app"):
    """Make a directory and register it as a project."""
    directory = tmp_path / "work" / name
    directory.mkdir(parents=True)
    (directory / "keep.txt").write_bytes(b"keep")

    added = run_cli(monkeypatch, tmp_path, "project", "add", str(directory))

    assert added == 0

    return directory


def _add_goal(tmp_path, project="app"):
    goal = Goal.create(description="Do something", project=project)
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)

    return goal


def _grants(tmp_path):
    return PermissionRegistry.beside(tmp_path / "tasks.json")


def _state(tmp_path):
    return (tmp_path / "projects.json").read_bytes()


def test_a_project_is_removed_and_its_directory_is_not(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The registry entry goes, and the files stay."""
    directory = _register(monkeypatch, tmp_path)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 0

    output = capsys.readouterr().out

    assert "Project removed: app" in output
    assert f"Path: {directory.resolve()}" in output
    assert "The directory was not touched." in output
    assert (directory / "keep.txt").read_bytes() == b"keep"

    assert run_cli(monkeypatch, tmp_path, "project", "list") == 0
    assert "No projects registered." in capsys.readouterr().out


def test_validation_passes_after_a_project_is_removed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Nothing is left that points at the removed project."""
    _register(monkeypatch, tmp_path)
    _register(monkeypatch, tmp_path, "lib")

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 0
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "validate") == 0
    assert "Validation passed." in capsys.readouterr().out
    assert run_cli(monkeypatch, tmp_path, "project", "list") == 0
    assert "- lib" in capsys.readouterr().out


def test_an_unknown_project_is_refused_and_nothing_is_written(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The error names the project."""
    _register(monkeypatch, tmp_path)
    before = _state(tmp_path)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "nope") == 1

    assert "Error: no project named nope is registered" in (
        capsys.readouterr().out
    )
    assert _state(tmp_path) == before


def test_an_empty_name_is_refused(tmp_path, monkeypatch, capsys) -> None:
    """A blank name is not a project."""
    assert run_cli(monkeypatch, tmp_path, "project", "remove", "  ") == 1

    assert "project name cannot be empty" in capsys.readouterr().out
    assert not (tmp_path / "projects.json").exists()


def test_a_project_with_a_goal_stays(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The goal is named, and nothing is changed."""
    _register(monkeypatch, tmp_path)
    goal = _add_goal(tmp_path)
    before = _state(tmp_path)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 1

    output = capsys.readouterr().out

    assert "Error: project app cannot be removed" in output
    assert "Goals that use it: 1" in output
    assert f"- {goal.id} (pending)" in output
    assert "Nothing was changed." in output
    assert "Goals cannot be removed yet" in output
    assert "aic permission revoke" not in output
    assert _state(tmp_path) == before


def test_only_the_first_goals_are_listed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Seven goals are counted, five are shown, and two are summed up."""
    _register(monkeypatch, tmp_path)
    goals = [_add_goal(tmp_path) for _ in range(7)]
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 1

    output = capsys.readouterr().out

    assert "Goals that use it: 7" in output
    assert "  and 2 more" in output
    assert sum(1 for goal in goals if f"- {goal.id} " in output) == 5


def test_exactly_five_goals_are_listed_with_no_summary(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Nothing is hidden, so nothing is said to be left out."""
    _register(monkeypatch, tmp_path)
    goals = [_add_goal(tmp_path) for _ in range(5)]
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 1

    output = capsys.readouterr().out

    assert "Goals that use it: 5" in output
    assert all(f"- {goal.id} " in output for goal in goals)
    assert " more" not in output


def test_a_goal_of_another_project_does_not_block(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Only the goals that name the project count."""
    _register(monkeypatch, tmp_path)
    _register(monkeypatch, tmp_path, "lib")
    _add_goal(tmp_path, "lib")
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 0


def test_a_grant_blocks_until_it_is_revoked(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The refusal says how to withdraw the grant, and that works."""
    _register(monkeypatch, tmp_path)
    _grants(tmp_path).grant("app", "inspect", "look at it")
    before = _state(tmp_path)
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 1

    output = capsys.readouterr().out

    assert "Active grants: 1" in output
    assert "- target inspect" in output
    assert "Withdraw a grant with: aic permission revoke app" in output
    assert "Goals cannot be removed yet" not in output
    assert _state(tmp_path) == before

    assert run_cli(
        monkeypatch,
        tmp_path,
        "permission",
        "revoke",
        "app",
        "--target",
        "inspect",
    ) == 0
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 0
    assert "Project removed: app" in capsys.readouterr().out


def test_a_goal_and_a_grant_are_both_reported(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Both kinds of blocker are in one refusal."""
    _register(monkeypatch, tmp_path)
    _add_goal(tmp_path)
    _grants(tmp_path).grant("app", "inspect", "look at it")
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 1

    output = capsys.readouterr().out

    assert "Goals that use it: 1" in output
    assert "Active grants: 1" in output


def _two_projects_named_app(tmp_path):
    """Write a registry that holds one name twice, as an edit could."""
    first = tmp_path / "one" / "app"
    second = tmp_path / "two" / "app"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
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

    return first, second


def test_a_shared_name_needs_the_directory(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Both directories are shown, and nothing is changed."""
    first, second = _two_projects_named_app(tmp_path)
    before = _state(tmp_path)

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 1

    output = capsys.readouterr().out

    assert "2 projects are named app" in output
    assert str(first) in output
    assert str(second) in output
    assert "aic project remove <name> --path <directory>" in output
    assert _state(tmp_path) == before


def test_the_directory_removes_one_of_a_shared_name(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The other entry stays, so a goal and a grant do not block."""
    first, second = _two_projects_named_app(tmp_path)
    _add_goal(tmp_path)
    _grants(tmp_path).grant("app", "inspect", "look at it")

    assert run_cli(
        monkeypatch,
        tmp_path,
        "project",
        "remove",
        "app",
        "--path",
        str(second),
    ) == 0

    output = capsys.readouterr().out

    assert f"Path: {second}" in output
    assert run_cli(monkeypatch, tmp_path, "project", "list") == 0

    listing = capsys.readouterr().out

    assert str(first) in listing
    assert str(second) not in listing
    assert run_cli(monkeypatch, tmp_path, "validate") == 0


def test_a_directory_that_matches_nothing_is_refused(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The error says which directory was asked for."""
    _register(monkeypatch, tmp_path)
    other = tmp_path / "other"
    before = _state(tmp_path)
    capsys.readouterr()

    assert run_cli(
        monkeypatch,
        tmp_path,
        "project",
        "remove",
        "app",
        "--path",
        str(other),
    ) == 1

    assert f"no project named app is registered at {other}" in (
        capsys.readouterr().out
    )
    assert _state(tmp_path) == before


def test_a_project_whose_directory_is_gone_can_be_removed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Nothing about the directory is needed to remove the entry."""
    directory = _register(monkeypatch, tmp_path)
    (directory / "keep.txt").unlink()
    directory.rmdir()
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "project", "remove", "app") == 0
    assert "Project removed: app" in capsys.readouterr().out
