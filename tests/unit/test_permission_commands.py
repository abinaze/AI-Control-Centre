"""Tests for the permission commands."""

import pytest

from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.permissions.commands import (
    grant_permission,
    list_permissions,
    revoke_permission,
)
from aic_control_centre.permissions.model import Grant
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)


class NeedsGrant:
    """An adapter that says nothing about grants, so it needs one."""

    def execute(self, request):
        return ExecutionOutcome(
            task_id=request.task_id,
            outcome="completed",
            reason="ran",
        )


class NeedsNoGrant(NeedsGrant):
    requires_grant = False


def _setup(tmp_path, monkeypatch):
    """Register a project 'alpha' and the targets 'needs' and 'free'."""
    monkeypatch.setenv("AIC_DATA_DIR", str(tmp_path))
    project = tmp_path / "alpha"
    project.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(project)
    adapters = ExecutionAdapterRegistry()
    adapters.register("needs", NeedsGrant())
    adapters.register("free", NeedsNoGrant())
    monkeypatch.setattr(
        "aic_control_centre.permissions.commands.build_adapter_registry",
        lambda: adapters,
    )

    return PermissionRegistry(tmp_path / "permissions.json")


def _grant(tmp_path, monkeypatch, project="alpha", target="needs"):
    assert grant_permission(project, target, "trusted") == 0


def test_grant_records_the_permission_and_says_so(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A grant is stored and its details are printed."""
    registry = _setup(tmp_path, monkeypatch)

    assert grant_permission("alpha", "needs", "trusted") == 0

    output = capsys.readouterr().out
    [stored] = registry.list_grants()

    assert "Permission granted." in output
    assert f"ID: {stored.id}" in output
    assert "Project: alpha" in output
    assert "Target: needs" in output
    assert "Reason: trusted" in output
    assert registry.is_granted("alpha", "needs") is True


def test_grant_strips_names_and_reason(tmp_path, monkeypatch) -> None:
    """Stray space around the arguments is not stored."""
    registry = _setup(tmp_path, monkeypatch)

    assert grant_permission(" alpha ", " needs ", "  trusted  ") == 0

    [stored] = registry.list_grants()

    assert (stored.project, stored.target, stored.reason) == (
        "alpha",
        "needs",
        "trusted",
    )


def test_grant_refuses_an_unregistered_project(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A typo in the project is caught when the grant is made."""
    _setup(tmp_path, monkeypatch)

    assert grant_permission("ghost", "needs", "trusted") == 1

    output = capsys.readouterr().out

    assert "Error: project is not registered: ghost" in output
    assert "aic project add" in output
    assert not (tmp_path / "permissions.json").exists()


def test_grant_refuses_an_unregistered_target(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A typo in the target is caught when the grant is made."""
    _setup(tmp_path, monkeypatch)

    assert grant_permission("alpha", "shell", "trusted") == 1

    output = capsys.readouterr().out

    assert "Error: target is not registered: shell" in output
    assert "aic task targets" in output
    assert not (tmp_path / "permissions.json").exists()


@pytest.mark.parametrize(
    ("project", "target", "reason", "message"),
    [
        (" ", "needs", "trusted", "project cannot be empty"),
        ("alpha", " ", "trusted", "target cannot be empty"),
        ("alpha", "needs", " ", "reason cannot be empty"),
    ],
)
def test_grant_refuses_a_blank_argument(
    tmp_path,
    monkeypatch,
    capsys,
    project,
    target,
    reason,
    message,
) -> None:
    """Every argument is needed, and nothing is written without one."""
    _setup(tmp_path, monkeypatch)

    assert grant_permission(project, target, reason) == 1
    assert f"Error: {message}." in capsys.readouterr().out
    assert not (tmp_path / "permissions.json").exists()


def test_grant_refuses_a_pair_that_is_already_granted(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The same pair is not granted twice."""
    registry = _setup(tmp_path, monkeypatch)
    _grant(tmp_path, monkeypatch)
    capsys.readouterr()

    assert grant_permission("alpha", "needs", "again") == 1

    assert "already granted for project alpha" in capsys.readouterr().out
    assert len(registry.list_grants(include_revoked=True)) == 1


def test_a_revoked_pair_can_be_granted_again(tmp_path, monkeypatch) -> None:
    """Revoking and granting again keeps both in the history."""
    registry = _setup(tmp_path, monkeypatch)
    _grant(tmp_path, monkeypatch)
    assert revoke_permission("alpha", "needs") == 0

    assert grant_permission("alpha", "needs", "second") == 0

    assert len(registry.list_grants(include_revoked=True)) == 2
    assert registry.is_granted("alpha", "needs") is True


def test_grant_says_when_the_target_needs_no_grant(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A grant for a target that needs none is allowed and says so."""
    registry = _setup(tmp_path, monkeypatch)

    assert grant_permission("alpha", "free", "just in case") == 0

    assert "needs no grant, so this changes nothing" in (
        capsys.readouterr().out
    )
    assert registry.is_granted("alpha", "free") is True


def test_grant_says_nothing_extra_for_a_target_that_needs_one(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The note appears only when the grant is not needed."""
    _setup(tmp_path, monkeypatch)

    assert grant_permission("alpha", "needs", "trusted") == 0

    assert "Note:" not in capsys.readouterr().out


def test_revoke_ends_the_grant(tmp_path, monkeypatch, capsys) -> None:
    """A revoked grant no longer allows, and the output names it."""
    registry = _setup(tmp_path, monkeypatch)
    _grant(tmp_path, monkeypatch)
    [stored] = registry.list_grants()
    capsys.readouterr()

    assert revoke_permission("alpha", "needs") == 0

    output = capsys.readouterr().out

    assert "Permission revoked." in output
    assert "Project: alpha" in output
    assert "Target: needs" in output
    assert f"ID: {stored.id}" in output
    assert registry.is_granted("alpha", "needs") is False


def test_revoke_refuses_a_pair_that_is_not_granted(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Revoking nothing is an error and writes nothing."""
    _setup(tmp_path, monkeypatch)

    assert revoke_permission("alpha", "needs") == 1

    assert "not granted for project alpha" in capsys.readouterr().out
    assert not (tmp_path / "permissions.json").exists()


@pytest.mark.parametrize(
    ("project", "target", "message"),
    [
        (" ", "needs", "project cannot be empty"),
        ("alpha", " ", "target cannot be empty"),
    ],
)
def test_revoke_refuses_a_blank_argument(
    tmp_path,
    monkeypatch,
    capsys,
    project,
    target,
    message,
) -> None:
    """Both names are needed to revoke."""
    _setup(tmp_path, monkeypatch)

    assert revoke_permission(project, target) == 1
    assert f"Error: {message}." in capsys.readouterr().out


def test_a_grant_can_be_revoked_after_its_project_or_target_is_gone(
    tmp_path,
    monkeypatch,
) -> None:
    """A grant can always be withdrawn, whatever else has changed."""
    registry = _setup(tmp_path, monkeypatch)
    write_text_atomic(
        tmp_path / "permissions.json",
        serialize_state_items(
            "permissions",
            [
                {
                    "id": "old",
                    "project": "ghost",
                    "target": "gone",
                    "granted_at": "2026-01-01T00:00:00+00:00",
                    "reason": "trusted",
                    "revoked_at": None,
                },
            ],
        ),
    )

    assert revoke_permission("ghost", "gone") == 0
    assert registry.is_granted("ghost", "gone") is False


def test_list_says_when_nothing_is_granted(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """An empty state prints a plain message and writes nothing."""
    _setup(tmp_path, monkeypatch)

    assert list_permissions() == 0
    assert "No permissions granted." in capsys.readouterr().out

    assert list_permissions(include_revoked=True) == 0
    assert "No permissions recorded." in capsys.readouterr().out
    assert not (tmp_path / "permissions.json").exists()


def test_list_shows_active_grants_with_their_details(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Each grant is listed with who, what, why and when."""
    registry = _setup(tmp_path, monkeypatch)
    _grant(tmp_path, monkeypatch)
    [stored] = registry.list_grants()
    capsys.readouterr()

    assert list_permissions() == 0

    output = capsys.readouterr().out

    assert "Granted permissions:" in output
    assert f"- {stored.id}" in output
    assert "  Project: alpha" in output
    assert "  Target: needs" in output
    assert "  Status: active" in output
    assert "  Reason: trusted" in output
    assert f"  Granted: {stored.granted_at}" in output
    assert "Revoked:" not in output


def test_list_hides_revoked_grants_unless_asked(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The default listing shows what is allowed now."""
    registry = _setup(tmp_path, monkeypatch)
    _grant(tmp_path, monkeypatch)
    assert revoke_permission("alpha", "needs") == 0
    [stored] = registry.list_grants(include_revoked=True)
    capsys.readouterr()

    assert list_permissions() == 0
    assert "No permissions granted." in capsys.readouterr().out

    assert list_permissions(include_revoked=True) == 0

    output = capsys.readouterr().out

    assert "All permissions:" in output
    assert "  Status: revoked" in output
    assert f"  Revoked: {stored.revoked_at}" in output


def test_listing_does_not_modify_the_file(tmp_path, monkeypatch) -> None:
    """Listing only reads."""
    _setup(tmp_path, monkeypatch)
    _grant(tmp_path, monkeypatch)
    before = (tmp_path / "permissions.json").read_bytes()

    list_permissions(include_revoked=True)

    assert (tmp_path / "permissions.json").read_bytes() == before


def test_the_commands_agree_with_the_library(tmp_path, monkeypatch) -> None:
    """What the command stores is what the registry reads back."""
    registry = _setup(tmp_path, monkeypatch)
    _grant(tmp_path, monkeypatch)

    [stored] = registry.list_grants()

    assert isinstance(stored, Grant)
    assert stored.is_active is True
