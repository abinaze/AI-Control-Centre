"""Tests for the limits of a snapshot."""

import pytest

from aic_control_centre.execution import snapshot as snapshot_module
from aic_control_centre.execution.snapshot import (
    SnapshotLimitError,
    take_snapshot,
)

MEBIBYTE = 1024 * 1024


def _write(path, size=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _tree(tmp_path):
    """Make three files of 3, 5 and 7 bytes, at three depths."""
    _write(tmp_path / "a.txt", 3)
    _write(tmp_path / "sub" / "b.txt", 5)
    _write(tmp_path / "sub" / "deep" / "c.txt", 7)

    return tmp_path


def test_limits_that_are_not_passed_change_nothing(tmp_path) -> None:
    """The snapshot is the one that is taken with no limits."""
    _tree(tmp_path)

    limited = take_snapshot(tmp_path, max_files=3, max_bytes=15)

    assert limited == take_snapshot(tmp_path)


def test_too_many_files_stop_the_snapshot(tmp_path) -> None:
    """The error is an OSError that says which limit was passed."""
    _tree(tmp_path)

    with pytest.raises(SnapshotLimitError) as caught:
        take_snapshot(tmp_path, max_files=2)

    assert isinstance(caught.value, OSError)
    assert caught.value.strerror == "the project has more than 2 files"


def test_too_many_bytes_stop_the_snapshot(tmp_path) -> None:
    """The size is the size of the regular files together."""
    _tree(tmp_path)

    with pytest.raises(SnapshotLimitError) as caught:
        take_snapshot(tmp_path, max_bytes=14)

    assert caught.value.strerror == (
        "the project has more than 14 bytes in files"
    )


def test_a_size_in_mebibytes_is_told_in_mebibytes(tmp_path) -> None:
    """A limit of whole MiB is not told as a long number."""
    _write(tmp_path / "big.bin", 2 * MEBIBYTE)

    with pytest.raises(SnapshotLimitError) as caught:
        take_snapshot(tmp_path, max_bytes=MEBIBYTE)

    assert caught.value.strerror == (
        "the project has more than 1 MiB in files"
    )


def test_directories_do_not_count_towards_the_file_limit(tmp_path) -> None:
    """Only regular files are counted."""
    for number in range(5):
        (tmp_path / f"empty{number}").mkdir()

    assert len(take_snapshot(tmp_path, max_files=0, max_bytes=0)) == 5


def test_a_file_over_the_limit_is_not_opened(
    tmp_path,
    monkeypatch,
) -> None:
    """The snapshot stops before it hashes the file that passes a limit."""
    for number in range(6):
        _write(tmp_path / f"f{number}.txt")

    opened = []
    real = snapshot_module.file_digest

    def file_digest(path):
        opened.append(path)

        return real(path)

    monkeypatch.setattr(snapshot_module, "file_digest", file_digest)

    with pytest.raises(SnapshotLimitError):
        take_snapshot(tmp_path, max_files=2)

    assert len(opened) == 2


def test_the_files_limit_is_named_when_both_are_passed(tmp_path) -> None:
    """The same order as the survey."""
    _write(tmp_path / "a.txt", 5)

    with pytest.raises(SnapshotLimitError) as caught:
        take_snapshot(tmp_path, max_files=0, max_bytes=0)

    assert caught.value.strerror == "the project has more than 0 files"
