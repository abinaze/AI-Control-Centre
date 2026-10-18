"""Tests for grant checks in aic validate."""

import sys
from dataclasses import asdict

from aic_control_centre.cli import main
from aic_control_centre.permissions.model import Grant
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _register_project(tmp_path, name="alpha"):
    path = tmp_path / name
    path.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(path)


def _write_grant(tmp_path, project="alpha", target="noop"):
    grant = Grant(
        id="grant-1",
        project=project,
        target=target,
        granted_at="2026-01-01T00:00:00+00:00",
        reason="trusted",
    )
    write_text_atomic(
        tmp_path / "permissions.json",
        serialize_state_items("permissions", [asdict(grant)]),
    )


def test_validate_passes_with_a_grant_for_a_registered_target(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A grant that points at a project and a target that exist passes."""
    _register_project(tmp_path)
    _write_grant(tmp_path, target="noop")

    result = run_cli(monkeypatch, tmp_path, "validate")

    assert result == 0
    assert "Validation passed." in capsys.readouterr().out


def test_validate_reports_a_grant_for_a_target_the_code_lacks(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The CLI offers the targets that it really registers."""
    _register_project(tmp_path)
    _write_grant(tmp_path, target="shell")

    result = run_cli(monkeypatch, tmp_path, "validate")

    output = capsys.readouterr().out

    assert result == 1
    assert "Grant grant-1 references unregistered target: shell" in output


def test_validate_reports_a_grant_for_an_unregistered_project(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The CLI checks the project of a grant against the registry."""
    _write_grant(tmp_path, project="ghost", target="noop")

    result = run_cli(monkeypatch, tmp_path, "validate")

    output = capsys.readouterr().out

    assert result == 1
    assert "Grant grant-1 references unregistered project: ghost" in output


def test_validate_reports_an_unreadable_grants_file(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A damaged grants file ends the command with an error message."""
    (tmp_path / "permissions.json").write_text("{not json", encoding="utf-8")

    result = run_cli(monkeypatch, tmp_path, "validate")

    assert result == 1
    assert "permissions.json" in capsys.readouterr().out


def test_validate_does_not_create_the_grants_file(
    tmp_path,
    monkeypatch,
) -> None:
    """Validating a clean state writes no grants file."""
    assert run_cli(monkeypatch, tmp_path, "validate") == 0
    assert not (tmp_path / "permissions.json").exists()
