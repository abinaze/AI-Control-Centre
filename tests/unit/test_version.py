"""Tests that the package version is written down consistently."""

import tomllib
from pathlib import Path

import pytest

from aic_control_centre import __version__
from aic_control_centre.cli import build_parser


def test_cli_version_flag_prints_the_package_version(capsys) -> None:
    """aic --version reports the version the package declares."""
    with pytest.raises(SystemExit) as excinfo:
        build_parser().parse_args(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"aic {__version__}"


def test_pyproject_version_matches_the_package_version() -> None:
    """The two places the version is written must agree."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    assert data["project"]["version"] == __version__
