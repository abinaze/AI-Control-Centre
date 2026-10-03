"""Tests for atomic state file writing."""

import pytest

from aic_control_centre.storage import write_text_atomic


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
