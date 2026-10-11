"""Tests for atomic state file writing."""

import json
import os

import pytest

from aic_control_centre import storage
from aic_control_centre.storage import (
    REPLACE_ATTEMPTS,
    SCHEMA_VERSION,
    StateFileError,
    UnsupportedSchemaVersionError,
    read_state_items,
    serialize_state_items,
    write_text_atomic,
)


def _fail(*args, **kwargs) -> None:
    """Simulate an operating system failure."""
    raise OSError("simulated failure")


def _interrupt(*args, **kwargs) -> None:
    """Simulate the user interrupting the process."""
    raise KeyboardInterrupt


def test_write_text_atomic_creates_file(tmp_path) -> None:
    """A new file is created with the given content."""
    target = tmp_path / "state.json"

    write_text_atomic(target, '{"a": 1}')

    assert target.read_text(encoding="utf-8") == '{"a": 1}'


def test_write_text_atomic_replaces_existing_content(tmp_path) -> None:
    """New content fully replaces longer existing content."""
    target = tmp_path / "state.json"
    target.write_text("old content that is much longer", encoding="utf-8")

    write_text_atomic(target, "new")

    assert target.read_text(encoding="utf-8") == "new"


def test_write_text_atomic_leaves_no_temporary_files(tmp_path) -> None:
    """A successful write leaves only the target file behind."""
    target = tmp_path / "state.json"

    write_text_atomic(target, "one")
    write_text_atomic(target, "two")

    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


def test_write_text_atomic_round_trips_utf8(tmp_path) -> None:
    """Non-ASCII text is stored as UTF-8."""
    target = tmp_path / "state.json"
    text = "caf\u00e9 \u2713"

    write_text_atomic(target, text)

    assert target.read_text(encoding="utf-8") == text


def test_failed_replace_keeps_original_and_cleans_up(
    tmp_path,
    monkeypatch,
) -> None:
    """If the final replace fails, the original file is untouched."""
    target = tmp_path / "state.json"
    target.write_text("original", encoding="utf-8")
    monkeypatch.setattr("aic_control_centre.storage.os.replace", _fail)

    with pytest.raises(OSError, match="simulated failure"):
        write_text_atomic(target, "replacement")

    assert target.read_text(encoding="utf-8") == "original"
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


def test_failed_flush_keeps_original_and_cleans_up(
    tmp_path,
    monkeypatch,
) -> None:
    """If syncing to disk fails, the original file is untouched."""
    target = tmp_path / "state.json"
    target.write_text("original", encoding="utf-8")
    monkeypatch.setattr("aic_control_centre.storage.os.fsync", _fail)

    with pytest.raises(OSError, match="simulated failure"):
        write_text_atomic(target, "replacement")

    assert target.read_text(encoding="utf-8") == "original"
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


def test_interrupt_during_replace_cleans_up(tmp_path, monkeypatch) -> None:
    """An interrupt removes the temporary file and keeps the original."""
    target = tmp_path / "state.json"
    target.write_text("original", encoding="utf-8")
    monkeypatch.setattr("aic_control_centre.storage.os.replace", _interrupt)

    with pytest.raises(KeyboardInterrupt):
        write_text_atomic(target, "replacement")

    assert target.read_text(encoding="utf-8") == "original"
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


def test_missing_parent_directory_is_an_error(tmp_path) -> None:
    """The parent directory is not created implicitly."""
    target = tmp_path / "missing" / "state.json"

    with pytest.raises(FileNotFoundError):
        write_text_atomic(target, "content")

    assert not (tmp_path / "missing").exists()


def test_serialize_state_items_writes_version_first() -> None:
    """Serialized state names its schema version before its items."""
    data = json.loads(serialize_state_items("goals", [{"id": "g1"}]))

    assert data == {"schema_version": SCHEMA_VERSION, "goals": [{"id": "g1"}]}
    assert list(data) == ["schema_version", "goals"]


def test_read_state_items_round_trips_versioned_state(tmp_path) -> None:
    """Items written by serialize_state_items are read back unchanged."""
    path = tmp_path / "state.json"
    items = [{"id": "one"}, {"id": "two"}]
    path.write_text(serialize_state_items("tasks", items), encoding="utf-8")

    assert read_state_items(path, "tasks") == items


def test_read_state_items_reads_legacy_list_as_version_one(tmp_path) -> None:
    """A bare list written before versioning is still readable."""
    path = tmp_path / "state.json"
    path.write_text('[{"id": "old"}]', encoding="utf-8")

    assert read_state_items(path, "tasks") == [{"id": "old"}]


def test_read_state_items_does_not_modify_the_file(tmp_path) -> None:
    """Reading a legacy file leaves its bytes untouched."""
    path = tmp_path / "state.json"
    path.write_text('[{"id": "old"}]', encoding="utf-8")
    before = path.read_bytes()

    read_state_items(path, "tasks")

    assert path.read_bytes() == before


def test_read_state_items_refuses_newer_schema_version(tmp_path) -> None:
    """A file from a newer schema version is refused, not guessed at."""
    path = tmp_path / "state.json"
    text = json.dumps({"schema_version": SCHEMA_VERSION + 1, "tasks": []})
    path.write_text(text, encoding="utf-8")

    with pytest.raises(UnsupportedSchemaVersionError) as error:
        read_state_items(path, "tasks")

    assert f"schema version {SCHEMA_VERSION + 1}" in str(error.value)
    assert f"supports up to {SCHEMA_VERSION}" in str(error.value)
    assert path.read_text(encoding="utf-8") == text


def test_unsupported_version_error_is_a_state_file_error() -> None:
    """Callers can catch every state file problem with one exception."""
    assert issubclass(UnsupportedSchemaVersionError, StateFileError)
    assert issubclass(StateFileError, ValueError)


@pytest.mark.parametrize(
    "content",
    [
        "not json at all",
        "",
        '"just a string"',
        "42",
        '{"tasks": []}',
        '{"schema_version": "1", "tasks": []}',
        '{"schema_version": true, "tasks": []}',
        '{"schema_version": 0, "tasks": []}',
        '{"schema_version": 1}',
        '{"schema_version": 1, "tasks": {"id": "x"}}',
    ],
)
def test_read_state_items_rejects_malformed_files(tmp_path, content) -> None:
    """Files that are not valid state raise a StateFileError."""
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(StateFileError):
        read_state_items(path, "tasks")


def test_read_state_items_rejects_undecodable_bytes(tmp_path) -> None:
    """Bytes that are not UTF-8 raise a StateFileError."""
    path = tmp_path / "state.json"
    path.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(StateFileError):
        read_state_items(path, "tasks")


def test_replace_is_retried_after_a_permission_error(
    tmp_path,
    monkeypatch,
) -> None:
    """A brief permission error does not stop the write."""
    target = tmp_path / "state.json"
    target.write_text("original", encoding="utf-8")
    real_replace = os.replace
    calls = []

    def flaky_replace(source, destination):
        calls.append(source)

        if len(calls) <= 2:
            raise PermissionError("file is in use")

        real_replace(source, destination)

    monkeypatch.setattr(storage, "REPLACE_RETRY_DELAY", 0)
    monkeypatch.setattr(storage.os, "replace", flaky_replace)

    write_text_atomic(target, "replacement")

    assert len(calls) == 3
    assert target.read_text(encoding="utf-8") == "replacement"
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


def test_replace_gives_up_after_the_last_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    """A lasting permission error is raised and the original is kept."""
    target = tmp_path / "state.json"
    target.write_text("original", encoding="utf-8")
    calls = []

    def locked_replace(source, destination):
        calls.append(source)
        raise PermissionError("file is in use")

    monkeypatch.setattr(storage, "REPLACE_RETRY_DELAY", 0)
    monkeypatch.setattr(storage.os, "replace", locked_replace)

    with pytest.raises(PermissionError, match="file is in use"):
        write_text_atomic(target, "replacement")

    assert len(calls) == REPLACE_ATTEMPTS
    assert target.read_text(encoding="utf-8") == "original"
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


def test_replace_does_not_retry_other_errors(tmp_path, monkeypatch) -> None:
    """Only a permission error is worth retrying."""
    target = tmp_path / "state.json"
    target.write_text("original", encoding="utf-8")
    calls = []

    def broken_replace(source, destination):
        calls.append(source)
        raise OSError("simulated failure")

    monkeypatch.setattr(storage, "REPLACE_RETRY_DELAY", 0)
    monkeypatch.setattr(storage.os, "replace", broken_replace)

    with pytest.raises(OSError, match="simulated failure"):
        write_text_atomic(target, "replacement")

    assert len(calls) == 1
    assert target.read_text(encoding="utf-8") == "original"
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]
