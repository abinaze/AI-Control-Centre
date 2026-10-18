"""Tests for grant checks in goal task validation."""

from dataclasses import asdict

import pytest

from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.permissions.model import Grant
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.storage import (
    StateFileError,
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.validation.goal_tasks import GoalTaskValidator

TARGETS = ("noop", "shell")


def _grant(**changes):
    values = {
        "id": "grant-1",
        "project": "alpha",
        "target": "shell",
        "granted_at": "2026-01-01T00:00:00+00:00",
        "reason": "trusted",
        "revoked_at": None,
    }
    values.update(changes)

    return Grant(**values)


def _write_grants(tmp_path, *grants):
    """Write grants directly, bypassing the registry's own rules."""
    write_text_atomic(
        tmp_path / "permissions.json",
        serialize_state_items(
            "permissions",
            [asdict(grant) for grant in grants],
        ),
    )


def _validator(tmp_path, projects=True, targets=TARGETS, permissions=True):
    """Build a validator with a project 'alpha' and grants checked."""
    project_registry = None

    if projects:
        project_path = tmp_path / "alpha"
        project_path.mkdir()
        project_registry = ProjectRegistry(tmp_path / "projects.json")
        project_registry.add_project(project_path)

    return GoalTaskValidator(
        goal_registry=GoalRegistry(tmp_path / "goals.json"),
        task_registry=TaskRegistry(tmp_path / "tasks.json"),
        project_registry=project_registry,
        permission_registry=(
            PermissionRegistry(tmp_path / "permissions.json")
            if permissions
            else None
        ),
        known_targets=targets,
    )


def test_state_with_no_grants_is_valid(tmp_path) -> None:
    """A missing grants file is not a problem."""
    assert _validator(tmp_path).validate().valid is True


def test_an_active_grant_for_a_known_project_and_target_is_valid(
    tmp_path,
) -> None:
    """A grant that points at things that exist passes."""
    _write_grants(tmp_path, _grant())

    assert _validator(tmp_path).validate().valid is True


def test_a_revoked_grant_with_a_matching_active_grant_is_valid(
    tmp_path,
) -> None:
    """Revoked history alongside a new grant is not a duplicate."""
    _write_grants(
        tmp_path,
        _grant(id="old", revoked_at="2026-02-01T00:00:00+00:00"),
        _grant(id="new"),
    )

    assert _validator(tmp_path).validate().valid is True


def test_a_repeated_grant_id_is_reported(tmp_path) -> None:
    """Two grants may not share an ID."""
    _write_grants(
        tmp_path,
        _grant(id="same", target="shell"),
        _grant(id="same", target="noop"),
    )

    result = _validator(tmp_path).validate()

    assert result.errors == ("Duplicate grant ID: same",)


def test_a_grant_for_an_unregistered_project_is_reported(tmp_path) -> None:
    """A grant must point at a registered project."""
    _write_grants(tmp_path, _grant(id="g1", project="ghost"))

    result = _validator(tmp_path).validate()

    assert result.errors == (
        "Grant g1 references unregistered project: ghost",
    )


def test_a_grant_for_an_unregistered_target_is_reported(tmp_path) -> None:
    """A target that the code no longer registers is reported."""
    _write_grants(tmp_path, _grant(id="g1", target="removed"))

    result = _validator(tmp_path).validate()

    assert result.errors == (
        "Grant g1 references unregistered target: removed",
    )


def test_an_active_duplicate_is_reported(tmp_path) -> None:
    """Two active grants for one pair are reported once."""
    _write_grants(tmp_path, _grant(id="g1"), _grant(id="g2"))

    result = _validator(tmp_path).validate()

    assert result.errors == (
        "Grant g2 duplicates an active grant for target shell "
        "in project alpha",
    )


def test_a_revoked_grant_is_not_checked_against_projects_or_targets(
    tmp_path,
) -> None:
    """History is left alone once a grant no longer allows anything."""
    _write_grants(
        tmp_path,
        _grant(
            id="g1",
            project="ghost",
            target="removed",
            revoked_at="2026-02-01T00:00:00+00:00",
        ),
    )

    assert _validator(tmp_path).validate().valid is True


def test_every_problem_is_reported_together(tmp_path) -> None:
    """One run lists all the grant problems."""
    _write_grants(
        tmp_path,
        _grant(id="g1", project="ghost"),
        _grant(id="g2", target="removed"),
    )

    result = _validator(tmp_path).validate()

    assert len(result.errors) == 2


def test_grants_are_not_checked_without_a_registry(tmp_path) -> None:
    """Without a permission registry the file is left alone."""
    _write_grants(tmp_path, _grant(project="ghost", target="removed"))

    result = _validator(tmp_path, permissions=False).validate()

    assert result.valid is True


def test_projects_are_not_checked_without_a_project_registry(
    tmp_path,
) -> None:
    """Project names are only checked when there is a registry for them."""
    _write_grants(tmp_path, _grant(project="ghost"))

    result = _validator(tmp_path, projects=False).validate()

    assert result.valid is True


def test_targets_are_not_checked_without_a_list_of_targets(tmp_path) -> None:
    """Target names are only checked when the targets are given."""
    _write_grants(tmp_path, _grant(target="removed"))

    result = _validator(tmp_path, targets=None).validate()

    assert result.valid is True


def test_validation_does_not_modify_the_grants_file(tmp_path) -> None:
    """Validation only reads."""
    _write_grants(tmp_path, _grant(project="ghost"))
    before = (tmp_path / "permissions.json").read_bytes()

    _validator(tmp_path).validate()

    assert (tmp_path / "permissions.json").read_bytes() == before


def test_an_unreadable_grants_file_stops_validation(tmp_path) -> None:
    """A corrupt grants file is an error, not a silent pass."""
    (tmp_path / "permissions.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(StateFileError):
        _validator(tmp_path).validate()
