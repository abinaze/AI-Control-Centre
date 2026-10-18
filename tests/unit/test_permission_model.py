"""Tests for the grant model."""

import pytest

from aic_control_centre.permissions.model import Grant

VALID = {
    "id": "grant-1",
    "project": "alpha",
    "target": "shell",
    "granted_at": "2026-01-01T00:00:00+00:00",
    "reason": "trusted",
}


def test_create_records_the_project_target_and_reason() -> None:
    """A new grant is active and says what it allows and why."""
    grant = Grant.create(project="alpha", target="shell", reason="trusted")

    assert grant.project == "alpha"
    assert grant.target == "shell"
    assert grant.reason == "trusted"
    assert grant.granted_at
    assert grant.revoked_at is None
    assert grant.is_active is True


def test_create_strips_surrounding_whitespace() -> None:
    """Names and the reason are stored without surrounding space."""
    grant = Grant.create(
        project=" alpha ",
        target=" shell\n",
        reason="  trusted  ",
    )

    assert (grant.project, grant.target, grant.reason) == (
        "alpha",
        "shell",
        "trusted",
    )


def test_each_grant_gets_its_own_id() -> None:
    """Two grants for the same pair are told apart by their IDs."""
    first = Grant.create("alpha", "shell", "one")
    second = Grant.create("alpha", "shell", "two")

    assert first.id != second.id


@pytest.mark.parametrize("field", ["project", "target", "reason"])
def test_create_refuses_a_blank_field(field) -> None:
    """A grant needs a project, a target and a reason."""
    values = {"project": "alpha", "target": "shell", "reason": "ok"}
    values[field] = "   "

    with pytest.raises(ValueError, match=f"grant {field} cannot be empty"):
        Grant.create(**values)


@pytest.mark.parametrize(
    "field",
    ["id", "project", "target", "granted_at", "reason"],
)
def test_a_grant_built_directly_refuses_a_blank_field(field) -> None:
    """The rule also holds for a grant read back from a file."""
    values = {**VALID, field: ""}

    with pytest.raises(ValueError, match=f"grant {field} cannot be empty"):
        Grant(**values)


def test_a_field_that_is_not_text_is_refused() -> None:
    """A null in a hand-edited file is not mistaken for a value."""
    with pytest.raises(ValueError, match="grant reason cannot be empty"):
        Grant(**{**VALID, "reason": None})


def test_a_blank_revoked_at_is_refused() -> None:
    """A grant is revoked at a time or not at all."""
    with pytest.raises(ValueError, match="revoked_at cannot be empty"):
        Grant(**VALID, revoked_at="  ")


def test_revoke_sets_the_time_and_keeps_everything_else() -> None:
    """A revoked grant is no longer active and keeps its history."""
    grant = Grant(**VALID)

    revoked = grant.revoke()

    assert revoked.is_active is False
    assert revoked.revoked_at
    assert (revoked.id, revoked.project, revoked.target) == (
        grant.id,
        grant.project,
        grant.target,
    )
    assert (revoked.granted_at, revoked.reason) == (
        grant.granted_at,
        grant.reason,
    )
    assert grant.is_active is True


def test_revoking_a_revoked_grant_is_refused() -> None:
    """Only an active grant can be revoked."""
    revoked = Grant(**VALID).revoke()

    with pytest.raises(ValueError, match="already revoked"):
        revoked.revoke()
