"""Tests that the package metadata and the CLI describe the project alike."""

import tomllib
from pathlib import Path

from aic_control_centre.cli import build_parser


def _project_metadata() -> dict:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    return data["project"]


def test_pyproject_description_matches_the_cli_description() -> None:
    """The package metadata and aic --help say the same thing."""
    assert _project_metadata()["description"] == build_parser().description


def test_metadata_makes_no_claim_of_autonomy() -> None:
    """No autonomous behavior exists, so the metadata must not imply it."""
    metadata = _project_metadata()
    texts = [metadata["description"], build_parser().description]
    texts.extend(metadata["keywords"])

    assert [text for text in texts if "autonomous" in text.lower()] == []
