"""Tests for the file of archived goals."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from aic_control_centre.execution.records import ExecutionRecord
from aic_control_centre.goals import archive as archive_module
from aic_control_centre.goals.archive import ArchiveEntry, GoalArchive
from aic_control_centre.goals.model import Goal
from aic_control_centre.storage import (
    StateFileError,
    UnsupportedSchemaVersionError,
)
from aic_control_centre.tasks.model import Task


def _entry(title="first", project_path="/work/app", records=True):
    goal = Goal.create(description=title, project="app")
    tasks = [
        replace(Task.create(goal.id, f"{title} 1"), status="completed"),
        replace(Task.create(goal.id, f"{title} 2"), status="failed"),
    ]
    kept = []

    if records:
        kept = [
            ExecutionRecord(
                id=f"{task.id}-record",
                task_id=task.id,
                source="coordinator",
                target="noop",
                started_at="2026-10-30T00:00:00+00:00",
                ended_at="2026-10-30T00:00:01+00:00",
                ended_as=task.status,
                reason="why",
            )
            for task in tasks
        ]

    return ArchiveEntry.create(goal, tasks, kept, "tidy up", project_path)


def _archive(tmp_path):
    return GoalArchive(tmp_path / "archive.json")


def test_an_archive_that_is_not_there_is_empty(tmp_path) -> None:
    """Nothing is created by looking."""
    archive = _archive(tmp_path)

    assert archive.list_entries() == []
    assert archive.get_entry("nope") is None
    assert archive.has_goal("nope") is False
    assert not (tmp_path / "archive.json").exists()


def test_the_archive_is_stored_next_to_the_task_registry(tmp_path) -> None:
    """It is archive.json in the same directory as tasks.json."""
    archive = GoalArchive.beside(tmp_path / "data" / "tasks.json")

    assert archive.registry_path == tmp_path / "data" / "archive.json"


def test_an_entry_survives_a_round_trip_through_the_file(tmp_path) -> None:
    """A new object reads back exactly what was written."""
    entry = _entry()

    assert _archive(tmp_path).add_entry(entry) is True

    saved = _archive(tmp_path).list_entries()

    assert saved == [entry]
    assert saved[0].tasks == entry.tasks
    assert saved[0].records == entry.records
    assert _archive(tmp_path).get_entry(entry.goal.id) == entry
    assert _archive(tmp_path).has_goal(entry.goal.id) is True


def test_a_record_with_missing_fields_round_trips(tmp_path) -> None:
    """A record with no target and no start time is kept as it was."""
    goal = Goal.create(description="old", project="app")
    task = replace(Task.create(goal.id, "old"), status="completed")
    legacy = ExecutionRecord(
        id="legacy",
        task_id=task.id,
        source="cli",
        target=None,
        started_at=None,
        ended_at="2026-10-30T00:00:01+00:00",
        ended_as="completed",
        reason="",
    )
    entry = ArchiveEntry.create(goal, [task], [legacy], "tidy up", None)

    _archive(tmp_path).add_entry(entry)

    assert _archive(tmp_path).list_entries() == [entry]


def test_the_file_is_a_versioned_state_file(tmp_path) -> None:
    """It has the schema version and an archived list, like the others."""
    entry = _entry()

    _archive(tmp_path).add_entry(entry)

    data = json.loads((tmp_path / "archive.json").read_text("utf-8"))

    assert data["schema_version"] == 1
    assert [item["goal"]["id"] for item in data["archived"]] == [
        entry.goal.id,
    ]
    assert data["archived"][0]["project_path"] == "/work/app"
    assert data["archived"][0]["reason"] == "tidy up"


def test_entries_are_appended_in_order(tmp_path) -> None:
    """The oldest is first, and nothing that is there is changed."""
    entries = [_entry(name) for name in ("a", "b", "c", "d", "e")]
    archive = _archive(tmp_path)

    for entry in entries:
        assert archive.add_entry(entry) is True

    assert archive.list_entries() == entries


def test_a_goal_is_not_archived_twice(tmp_path) -> None:
    """The second write does nothing, and the file is the same bytes."""
    entry = _entry()
    archive = _archive(tmp_path)
    archive.add_entry(entry)
    before = (tmp_path / "archive.json").read_bytes()

    assert archive.add_entry(entry) is False
    assert (tmp_path / "archive.json").read_bytes() == before


def test_the_first_entry_of_a_goal_is_the_one_that_is_kept(tmp_path) -> None:
    """After a crash the active files may hold less, so a later entry for
    the same goal is smaller, and the complete one stays.
    """
    complete = _entry()
    smaller = ArchiveEntry.create(
        complete.goal,
        complete.tasks[:1],
        [],
        "again",
        None,
    )
    archive = _archive(tmp_path)
    archive.add_entry(complete)

    assert archive.add_entry(smaller) is False
    assert archive.get_entry(complete.goal.id) == complete


def test_the_directory_for_the_file_is_created(tmp_path) -> None:
    """The first entry may be the first file in the data directory."""
    archive = GoalArchive(tmp_path / "new" / "place" / "archive.json")

    archive.add_entry(_entry())

    assert (tmp_path / "new" / "place" / "archive.json").is_file()


def test_a_file_that_is_not_json_is_an_error_and_is_not_overwritten(
    tmp_path,
) -> None:
    """The entry is not written over something that cannot be read."""
    path = tmp_path / "archive.json"
    path.write_bytes(b"{ not json")
    archive = _archive(tmp_path)

    with pytest.raises(StateFileError, match="is not valid JSON"):
        archive.list_entries()

    with pytest.raises(StateFileError):
        archive.add_entry(_entry())

    assert path.read_bytes() == b"{ not json"


def test_a_newer_schema_version_is_refused_and_kept(tmp_path) -> None:
    """A file from a newer version is not guessed at or overwritten."""
    path = tmp_path / "archive.json"
    text = json.dumps({"schema_version": 999, "archived": []})
    path.write_text(text, encoding="utf-8")

    with pytest.raises(UnsupportedSchemaVersionError):
        _archive(tmp_path).add_entry(_entry())

    assert path.read_text("utf-8") == text


def test_an_entry_with_a_missing_field_is_an_error(tmp_path) -> None:
    """The error says that an archive entry is invalid, and the file stays."""
    path = tmp_path / "archive.json"
    text = json.dumps({"schema_version": 1, "archived": [{"goal": {}}]})
    path.write_text(text, encoding="utf-8")

    with pytest.raises(StateFileError, match="has an invalid archive entry"):
        _archive(tmp_path).list_entries()

    with pytest.raises(StateFileError):
        _archive(tmp_path).add_entry(_entry())

    assert path.read_text("utf-8") == text


def test_an_entry_that_holds_work_in_flight_is_invalid_in_the_file(
    tmp_path,
) -> None:
    """The rules of an entry apply to what is read, not just made."""
    entry = _entry()
    _archive(tmp_path).add_entry(entry)
    path = tmp_path / "archive.json"
    data = json.loads(path.read_text("utf-8"))
    data["archived"][0]["tasks"][0]["status"] = "running"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(StateFileError, match="only finished tasks"):
        _archive(tmp_path).list_entries()


def test_a_file_that_cannot_be_read_is_not_read_as_empty(
    tmp_path,
    monkeypatch,
) -> None:
    """A read error is an error. Writing over it would lose the history."""
    path = tmp_path / "archive.json"
    entry = _entry()
    _archive(tmp_path).add_entry(entry)
    before = path.read_bytes()
    real = Path.read_text

    def read_text(self, *arguments, **options):
        if self == path:
            raise PermissionError(13, "Permission denied")

        return real(self, *arguments, **options)

    monkeypatch.setattr(Path, "read_text", read_text)

    with pytest.raises(StateFileError, match="cannot be read"):
        _archive(tmp_path).add_entry(_entry("another"))

    monkeypatch.undo()

    assert path.read_bytes() == before


def test_the_file_is_found_even_if_path_exists_says_no(
    tmp_path,
    monkeypatch,
) -> None:
    """Whether the file is there is decided by reading it, not by exists()."""
    entry = _entry()
    _archive(tmp_path).add_entry(entry)
    path = tmp_path / "archive.json"
    real = Path.exists

    def exists(self, *arguments, **options):
        if self == path:
            return False

        return real(self, *arguments, **options)

    monkeypatch.setattr(Path, "exists", exists)

    assert _archive(tmp_path).list_entries() == [entry]
    assert _archive(tmp_path).add_entry(entry) is False


def test_a_failed_write_leaves_the_file_as_it_was(
    tmp_path,
    monkeypatch,
) -> None:
    """The error is raised and the entries that were there are kept."""
    first = _entry("first")
    archive = _archive(tmp_path)
    archive.add_entry(first)
    path = tmp_path / "archive.json"
    before = path.read_bytes()

    def refuse(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(archive_module, "write_text_atomic", refuse)

    with pytest.raises(OSError):
        archive.add_entry(_entry("second"))

    monkeypatch.undo()

    assert path.read_bytes() == before
    assert archive.list_entries() == [first]
