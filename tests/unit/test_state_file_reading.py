"""Tests for reading a state file that may not exist."""

import json
import pathlib

import pytest

from aic_control_centre.storage import (
    StateFileError,
    read_state_items,
    read_state_items_or_empty,
    serialize_state_items,
)


def _fail_reads(monkeypatch, path, error):
    """Make reading one file fail with an error, as a file system might."""
    real = pathlib.Path.read_text

    def read_text(self, *arguments, **options):
        if self == path:
            raise error

        return real(self, *arguments, **options)

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)


def test_a_missing_file_is_an_empty_list(tmp_path) -> None:
    """No file means nothing has been saved yet."""
    assert read_state_items_or_empty(tmp_path / "none.json", "tasks") == []


def test_a_path_below_a_file_is_an_empty_list(tmp_path) -> None:
    """Nothing can be saved below a file, so nothing is there."""
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")

    path = tmp_path / "file.txt" / "tasks.json"

    assert read_state_items_or_empty(path, "tasks") == []


def test_a_file_that_is_there_is_read(tmp_path) -> None:
    """Versioned files and legacy lists are read as they were."""
    versioned = tmp_path / "versioned.json"
    legacy = tmp_path / "legacy.json"
    versioned.write_text(
        serialize_state_items("tasks", [{"id": "a"}]),
        encoding="utf-8",
    )
    legacy.write_text(json.dumps([{"id": "b"}]), encoding="utf-8")

    assert read_state_items_or_empty(versioned, "tasks") == [{"id": "a"}]
    assert read_state_items_or_empty(legacy, "tasks") == [{"id": "b"}]


def test_an_unreadable_file_is_an_error_and_not_an_empty_list(
    tmp_path,
    monkeypatch,
) -> None:
    """An empty list here would let the next save overwrite the file."""
    path = tmp_path / "tasks.json"
    path.write_text(serialize_state_items("tasks", [{"id": "a"}]), "utf-8")
    _fail_reads(monkeypatch, path, PermissionError(13, "Access is denied"))

    with pytest.raises(StateFileError) as error:
        read_state_items_or_empty(path, "tasks")

    assert str(error.value) == f"{path} cannot be read: Access is denied"


def test_reading_a_file_that_cannot_be_read_gives_the_same_error(
    tmp_path,
    monkeypatch,
) -> None:
    """The plain reader says the same, so no caller sees a traceback."""
    path = tmp_path / "tasks.json"
    path.write_text(serialize_state_items("tasks", []), encoding="utf-8")
    _fail_reads(monkeypatch, path, OSError())

    with pytest.raises(StateFileError, match="cannot be read: OSError"):
        read_state_items(path, "tasks")


def test_a_missing_file_is_still_an_error_for_the_plain_reader(
    tmp_path,
) -> None:
    """Only the reader that is told a file may be absent accepts that."""
    with pytest.raises(FileNotFoundError):
        read_state_items(tmp_path / "none.json", "tasks")


def test_a_file_is_read_whatever_pathlib_says_about_it(
    tmp_path,
    monkeypatch,
) -> None:
    """Path.exists() hides errors on some Pythons, so it is not used."""
    path = tmp_path / "tasks.json"
    path.write_text(serialize_state_items("tasks", [{"id": "a"}]), "utf-8")
    real = pathlib.Path.exists

    def exists(self, **options):
        return False if self == path else real(self, **options)

    monkeypatch.setattr(pathlib.Path, "exists", exists)

    assert read_state_items_or_empty(path, "tasks") == [{"id": "a"}]


def test_text_that_is_not_utf8_is_still_not_valid_json(tmp_path) -> None:
    """A damaged file is an error, as it was before."""
    path = tmp_path / "tasks.json"
    path.write_bytes(b"\xff\xfe\x00bad")

    with pytest.raises(StateFileError, match="is not valid JSON"):
        read_state_items_or_empty(path, "tasks")


def test_damaged_json_is_still_an_error(tmp_path) -> None:
    """A damaged file is never an empty list."""
    path = tmp_path / "tasks.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(StateFileError, match="is not valid JSON"):
        read_state_items_or_empty(path, "tasks")


def test_reading_does_not_change_the_file(tmp_path) -> None:
    """Looking at a state file never writes to it."""
    path = tmp_path / "tasks.json"
    path.write_text(serialize_state_items("tasks", [{"id": "a"}]), "utf-8")
    before = path.read_bytes()

    read_state_items_or_empty(path, "tasks")

    assert path.read_bytes() == before
