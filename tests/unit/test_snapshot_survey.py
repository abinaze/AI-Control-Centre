"""Tests for the survey of a project directory."""

import os

import pytest

from aic_control_centre.execution import snapshot as snapshot_module
from aic_control_centre.execution.snapshot import (
    LIMIT_BYTES,
    LIMIT_FILES,
    SNAPSHOT_MAX_BYTES,
    SNAPSHOT_MAX_FILES,
    Survey,
    limit_text,
    survey_project,
)

BIG = 10**9


def _write(path, size=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _tree(tmp_path):
    """Make three files of 3, 5 and 7 bytes, at three depths."""
    _write(tmp_path / "a.txt", 3)
    _write(tmp_path / "sub" / "b.txt", 5)
    _write(tmp_path / "sub" / "deep" / "c.txt", 7)

    return tmp_path


def test_the_limits_are_the_ones_in_the_design_note() -> None:
    """Changing them means changing docs/SNAPSHOT_LIMIT_DESIGN.md."""
    assert SNAPSHOT_MAX_FILES == 20000
    assert SNAPSHOT_MAX_BYTES == 256 * 1024 * 1024


def test_a_survey_counts_the_files_and_their_size(tmp_path) -> None:
    """The count includes files at every depth."""
    survey = survey_project(_tree(tmp_path), BIG, BIG)

    assert survey.files == 3
    assert survey.size == 15
    assert survey.exceeded == ""


def test_directories_are_not_counted_as_files(tmp_path) -> None:
    """Empty directories add nothing."""
    _write(tmp_path / "one.txt", 4)
    (tmp_path / "empty").mkdir()
    (tmp_path / "also" / "empty").mkdir(parents=True)

    survey = survey_project(tmp_path, BIG, BIG)

    assert (survey.files, survey.size) == (1, 4)


def test_an_empty_directory_has_nothing_to_count(tmp_path) -> None:
    assert survey_project(tmp_path, 0, 0) == Survey(0, 0)


def test_exactly_at_the_file_limit_is_accepted(tmp_path) -> None:
    """A limit of 3 allows 3 files and refuses a fourth."""
    _tree(tmp_path)

    assert survey_project(tmp_path, 3, BIG).exceeded == ""

    _write(tmp_path / "d.txt")

    assert survey_project(tmp_path, 3, BIG).exceeded == LIMIT_FILES


def test_exactly_at_the_byte_limit_is_accepted(tmp_path) -> None:
    """A limit of 15 bytes allows 15 bytes and refuses 16."""
    _tree(tmp_path)

    assert survey_project(tmp_path, BIG, 15).exceeded == ""
    assert survey_project(tmp_path, BIG, 14).exceeded == LIMIT_BYTES


def test_the_files_limit_is_named_when_both_are_passed(tmp_path) -> None:
    """One file that passes both limits is reported as too many files."""
    _write(tmp_path / "a.txt", 5)

    assert survey_project(tmp_path, 0, 0).exceeded == LIMIT_FILES


def test_a_survey_stops_as_soon_as_a_limit_is_passed(
    tmp_path,
    monkeypatch,
) -> None:
    """Thirty directories are not all read when two files are the limit."""
    for number in range(30):
        _write(tmp_path / f"d{number:02d}" / "f.txt")

    calls = []
    real = snapshot_module.os.scandir

    def scandir(path):
        calls.append(path)

        return real(path)

    monkeypatch.setattr(snapshot_module.os, "scandir", scandir)

    survey = survey_project(tmp_path, 2, BIG)

    assert survey.exceeded == LIMIT_FILES
    assert len(calls) <= 5


def test_a_link_is_not_followed(tmp_path) -> None:
    """A link to a large directory adds nothing.

    This checks nothing where a link cannot be made, as for an account on
    Windows that may not create symbolic links.
    """
    outside = tmp_path / "outside"
    for number in range(5):
        _write(outside / f"f{number}.txt")

    project = tmp_path / "project"
    _write(project / "own.txt")

    try:
        os.symlink(outside, project / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        return

    assert survey_project(project, BIG, BIG).files == 1


def test_a_directory_that_cannot_be_read_is_skipped(
    tmp_path,
    monkeypatch,
) -> None:
    """Below the root, an unreadable directory is not an error."""
    _write(tmp_path / "ok" / "a.txt")
    _write(tmp_path / "locked" / "b.txt")
    real = snapshot_module.os.scandir

    def scandir(path):
        if os.path.basename(os.fspath(path)) == "locked":
            raise PermissionError(13, "Access is denied")

        return real(path)

    monkeypatch.setattr(snapshot_module.os, "scandir", scandir)

    survey = survey_project(tmp_path, BIG, BIG)

    assert survey.files == 1
    assert survey.exceeded == ""


def test_a_root_that_cannot_be_read_is_an_error(tmp_path) -> None:
    """The directory of the project itself must be readable."""
    with pytest.raises(OSError):
        survey_project(tmp_path / "gone", BIG, BIG)


def test_the_folders_are_ordered_by_count_and_then_by_name(
    tmp_path,
) -> None:
    """The order is fixed, so that the reason is the same every time."""
    for number in range(5):
        _write(tmp_path / "big" / "x" / f"f{number}.txt")

    for number in range(3):
        _write(tmp_path / "mid" / f"f{number}.txt")

    _write(tmp_path / "tiny" / "f.txt")
    _write(tmp_path / "small" / "f.txt")

    for number in range(4):
        _write(tmp_path / f"loose{number}.txt")

    survey = survey_project(tmp_path, BIG, BIG)

    assert survey.folders == (("big", 5), ("mid", 3), ("small", 1))


def test_files_in_the_root_are_not_a_folder(tmp_path) -> None:
    """A project with only loose files names no folder."""
    for number in range(3):
        _write(tmp_path / f"f{number}.txt")

    assert survey_project(tmp_path, BIG, BIG).folders == ()


def test_a_limit_is_told_in_words() -> None:
    """The words are used in the reasons that people read."""
    assert limit_text(LIMIT_FILES, 20000) == "20,000 files"
    assert limit_text(LIMIT_BYTES, 256 * 1024 * 1024) == "256 MiB in files"
    assert limit_text(LIMIT_BYTES, 1500) == "1,500 bytes in files"
    assert limit_text(LIMIT_BYTES, 1024 * 1024 + 1) == (
        "1,048,577 bytes in files"
    )
