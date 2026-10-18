"""Tests for the persistent grant registry."""

import json
from dataclasses import asdict

import pytest

from aic_control_centre.permissions.model import Grant
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.storage import (
    StateFileError,
    UnsupportedSchemaVersionError,
    serialize_state_items,
    write_text_atomic,
)


def _registry(tmp_path):
    return PermissionRegistry(tmp_path / "permissions.json")


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


def _write(tmp_path, grants):
    """Write grants directly, bypassing the registry's own rules."""
    write_text_atomic(
        tmp_path / "permissions.json",
        serialize_state_items("permissions", [asdict(g) for g in grants]),
    )


def test_a_missing_file_means_no_grants(tmp_path) -> None:
    """Reading an absent file grants nothing and does not create it."""
    registry = _registry(tmp_path)

    assert registry.list_grants() == []
    assert registry.is_granted("alpha", "shell") is False
    assert not (tmp_path / "permissions.json").exists()


def test_a_grant_is_stored_and_found_again(tmp_path) -> None:
    """A grant survives a new registry object on the same file."""
    grant = _registry(tmp_path).grant("alpha", "shell", "trusted")

    reread = _registry(tmp_path)

    assert reread.list_grants() == [grant]
    assert reread.is_granted("alpha", "shell") is True


def test_the_file_is_versioned_and_holds_every_field(tmp_path) -> None:
    """The file follows the shared state format."""
    _registry(tmp_path).grant("alpha", "shell", "trusted")

    data = json.loads((tmp_path / "permissions.json").read_text("utf-8"))

    assert data["schema_version"] == 1
    assert [set(item) for item in data["permissions"]] == [
        {"id", "project", "target", "granted_at", "reason", "revoked_at"},
    ]
    assert data["permissions"][0]["revoked_at"] is None


def test_names_and_reason_are_stored_stripped(tmp_path) -> None:
    """A grant made with stray space still matches the plain names."""
    registry = _registry(tmp_path)

    grant = registry.grant(" alpha ", " shell ", "  trusted  ")

    assert (grant.project, grant.target, grant.reason) == (
        "alpha",
        "shell",
        "trusted",
    )
    assert registry.is_granted("alpha", "shell") is True


@pytest.mark.parametrize(
    "values",
    [
        {"project": " ", "target": "shell", "reason": "ok"},
        {"project": "alpha", "target": " ", "reason": "ok"},
        {"project": "alpha", "target": "shell", "reason": " "},
    ],
)
def test_a_grant_with_a_blank_field_is_refused_and_writes_nothing(
    tmp_path,
    values,
) -> None:
    """A refused grant leaves no file behind."""
    with pytest.raises(ValueError, match="cannot be empty"):
        _registry(tmp_path).grant(**values)

    assert not (tmp_path / "permissions.json").exists()


def test_an_active_duplicate_is_refused(tmp_path) -> None:
    """A pair that is already granted is not granted a second time."""
    registry = _registry(tmp_path)
    registry.grant("alpha", "shell", "first")
    before = (tmp_path / "permissions.json").read_bytes()

    with pytest.raises(ValueError, match="already granted for project alpha"):
        registry.grant("alpha", "shell", "second")

    assert (tmp_path / "permissions.json").read_bytes() == before
    assert len(registry.list_grants(include_revoked=True)) == 1


def test_a_grant_covers_only_its_project_and_target(tmp_path) -> None:
    """A grant for one pair does not allow a neighbouring pair."""
    registry = _registry(tmp_path)
    registry.grant("alpha", "shell", "trusted")

    assert registry.is_granted("alpha", "shell") is True
    assert registry.is_granted("beta", "shell") is False
    assert registry.is_granted("alpha", "browser") is False


def test_the_same_target_can_be_granted_to_another_project(tmp_path) -> None:
    """Grants are per project, and per target."""
    registry = _registry(tmp_path)
    registry.grant("alpha", "shell", "one")

    registry.grant("beta", "shell", "two")
    registry.grant("alpha", "browser", "three")

    assert len(registry.list_grants()) == 3


def test_revoke_ends_the_grant_and_keeps_the_record(tmp_path) -> None:
    """A revoked grant stops allowing and stays as history."""
    registry = _registry(tmp_path)
    granted = registry.grant("alpha", "shell", "trusted")

    revoked = registry.revoke("alpha", "shell")

    assert [grant.id for grant in revoked] == [granted.id]
    assert registry.is_granted("alpha", "shell") is False

    history = registry.list_grants(include_revoked=True)

    assert [grant.id for grant in history] == [granted.id]
    assert history[0].revoked_at
    assert history[0].reason == "trusted"


def test_list_hides_revoked_grants_unless_asked(tmp_path) -> None:
    """The default listing shows what is allowed now."""
    registry = _registry(tmp_path)
    registry.grant("alpha", "shell", "one")
    registry.grant("alpha", "browser", "two")
    registry.revoke("alpha", "shell")

    assert [grant.target for grant in registry.list_grants()] == ["browser"]
    assert [
        grant.target for grant in registry.list_grants(include_revoked=True)
    ] == ["shell", "browser"]


def test_a_revoked_pair_can_be_granted_again(tmp_path) -> None:
    """The history keeps both grants and only the new one is active."""
    registry = _registry(tmp_path)
    first = registry.grant("alpha", "shell", "first")
    registry.revoke("alpha", "shell")

    second = registry.grant("alpha", "shell", "second")

    history = registry.list_grants(include_revoked=True)

    assert [grant.id for grant in history] == [first.id, second.id]
    assert [grant.is_active for grant in history] == [False, True]
    assert registry.is_granted("alpha", "shell") is True


def test_revoking_something_that_is_not_granted_is_refused(tmp_path) -> None:
    """A revoke of a missing grant changes nothing."""
    registry = _registry(tmp_path)

    with pytest.raises(ValueError, match="not granted for project alpha"):
        registry.revoke("alpha", "shell")

    assert not (tmp_path / "permissions.json").exists()


def test_revoking_twice_is_refused(tmp_path) -> None:
    """The second revoke finds nothing active."""
    registry = _registry(tmp_path)
    registry.grant("alpha", "shell", "trusted")
    registry.revoke("alpha", "shell")
    before = (tmp_path / "permissions.json").read_bytes()

    with pytest.raises(ValueError, match="not granted for project alpha"):
        registry.revoke("alpha", "shell")

    assert (tmp_path / "permissions.json").read_bytes() == before


def test_revoke_leaves_other_grants_active(tmp_path) -> None:
    """A revoke ends one pair and no other."""
    registry = _registry(tmp_path)
    registry.grant("alpha", "shell", "one")
    registry.grant("beta", "shell", "two")
    registry.grant("alpha", "browser", "three")

    registry.revoke("alpha", "shell")

    assert registry.is_granted("beta", "shell") is True
    assert registry.is_granted("alpha", "browser") is True


def test_revoke_ends_every_active_grant_for_the_pair(tmp_path) -> None:
    """A file edited into holding two active grants is fully revoked."""
    _write(
        tmp_path,
        [_grant(id="grant-1"), _grant(id="grant-2")],
    )
    registry = _registry(tmp_path)

    revoked = registry.revoke("alpha", "shell")

    assert len(revoked) == 2
    assert registry.is_granted("alpha", "shell") is False


def test_a_listing_does_not_modify_the_file(tmp_path) -> None:
    """Reading never writes."""
    registry = _registry(tmp_path)
    registry.grant("alpha", "shell", "trusted")
    before = (tmp_path / "permissions.json").read_bytes()

    registry.list_grants(include_revoked=True)
    registry.is_granted("alpha", "shell")

    assert (tmp_path / "permissions.json").read_bytes() == before


def test_beside_places_the_file_next_to_the_task_file(tmp_path) -> None:
    """The registry shares the directory of the other state files."""
    registry = PermissionRegistry.beside(tmp_path / "tasks.json")

    assert registry.registry_path == tmp_path / "permissions.json"


def test_a_bare_list_is_read_as_version_one(tmp_path) -> None:
    """A file with no version wrapper is read like the other state files."""
    (tmp_path / "permissions.json").write_text(
        json.dumps([asdict(_grant())]),
        encoding="utf-8",
    )

    assert _registry(tmp_path).is_granted("alpha", "shell") is True


def test_a_newer_schema_version_is_refused(tmp_path) -> None:
    """A file from a newer version is an error, never an empty answer."""
    (tmp_path / "permissions.json").write_text(
        json.dumps({"schema_version": 99, "permissions": []}),
        encoding="utf-8",
    )

    with pytest.raises(UnsupportedSchemaVersionError):
        _registry(tmp_path).is_granted("alpha", "shell")


@pytest.mark.parametrize(
    "item",
    [
        {"id": "g", "project": "alpha", "target": "shell"},
        {**asdict(_grant()), "reason": ""},
        {**asdict(_grant()), "revoked_at": " "},
        "not an object",
    ],
)
def test_an_invalid_grant_in_the_file_is_an_error(tmp_path, item) -> None:
    """A damaged record stops the read instead of being skipped."""
    (tmp_path / "permissions.json").write_text(
        json.dumps({"schema_version": 1, "permissions": [item]}),
        encoding="utf-8",
    )

    with pytest.raises(StateFileError, match="invalid grant"):
        _registry(tmp_path).list_grants(include_revoked=True)
