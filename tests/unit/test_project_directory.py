"""Tests for the project directory check."""

import os
import pathlib
from pathlib import Path

from aic_control_centre.projects import directory as directory_module
from aic_control_centre.projects.directory import (
    MISSING,
    NOT_A_DIRECTORY,
    UNREADABLE,
    directory_problem,
)


def _fail_for(monkeypatch, path, error):
    """Make os.stat raise an error for one path, as a file system might."""
    real = os.stat

    def stat(target, *arguments, **options):
        if os.fspath(target) == str(path):
            raise error

        return real(target, *arguments, **options)

    monkeypatch.setattr(directory_module.os, "stat", stat)


def test_a_directory_has_no_problem(tmp_path) -> None:
    """A directory that can be looked at is usable."""
    assert directory_problem(tmp_path) is None


def test_a_missing_path_is_missing(tmp_path) -> None:
    """Nothing there means missing, with no detail."""
    assert directory_problem(tmp_path / "gone") == (MISSING, "")


def test_a_file_is_not_a_directory(tmp_path) -> None:
    """Something else there is said to be something else."""
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")

    assert directory_problem(tmp_path / "file.txt") == (NOT_A_DIRECTORY, "")


def test_a_path_below_a_file_is_missing(tmp_path) -> None:
    """Nothing can be below a file, so nothing is there."""
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")

    assert directory_problem(tmp_path / "file.txt" / "below") == (MISSING, "")


def test_an_error_that_is_not_not_found_is_unreadable(
    tmp_path,
    monkeypatch,
) -> None:
    """The system's own reason is kept, and it is not called missing."""
    _fail_for(
        monkeypatch,
        tmp_path,
        PermissionError(13, "Access is denied"),
    )

    assert directory_problem(tmp_path) == (UNREADABLE, "Access is denied")


def test_an_error_without_a_reason_is_named(tmp_path, monkeypatch) -> None:
    """The name of the error stands in when the system gave no text."""
    _fail_for(monkeypatch, tmp_path, OSError())

    assert directory_problem(tmp_path) == (UNREADABLE, "OSError")


def test_a_path_that_cannot_be_looked_at_at_all_is_unreadable() -> None:
    """A name that the system rejects is a reason, not a crash."""
    assert directory_problem(Path("bad\x00name")) == (
        UNREADABLE,
        "ValueError",
    )


def test_not_found_is_missing_even_when_it_is_raised_by_the_system(
    tmp_path,
    monkeypatch,
) -> None:
    """The two errors that mean nothing is there are not unreadable."""
    _fail_for(monkeypatch, tmp_path, FileNotFoundError(2, "No such file"))

    assert directory_problem(tmp_path) == (MISSING, "")


def test_the_check_does_not_depend_on_pathlib_exists(
    tmp_path,
    monkeypatch,
) -> None:
    """Path.exists() and Path.is_dir() are not used for the answer."""
    monkeypatch.setattr(pathlib.Path, "exists", lambda self, **options: False)
    monkeypatch.setattr(pathlib.Path, "is_dir", lambda self, **options: False)

    assert directory_problem(tmp_path) is None
