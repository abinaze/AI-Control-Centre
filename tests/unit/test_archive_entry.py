"""Tests for the archive entry of a finished goal."""

from dataclasses import replace
from datetime import datetime

import pytest

from aic_control_centre.execution.records import ExecutionRecord
from aic_control_centre.goals.archive import ArchiveEntry
from aic_control_centre.goals.model import Goal
from aic_control_centre.tasks.model import Task


def _goal():
    return Goal.create(description="Ship it", project="app")


def _task(goal, title="first", status="completed"):
    return replace(Task.create(goal.id, title), status=status)


def _record(task, ended_as="completed", target="noop"):
    return ExecutionRecord(
        id=f"record-{task.id}",
        task_id=task.id,
        source="coordinator",
        target=target,
        started_at="2026-10-30T00:00:00+00:00",
        ended_at="2026-10-30T00:00:01+00:00",
        ended_as=ended_as,
        reason="done",
    )


def test_an_entry_holds_a_goal_its_tasks_and_their_records() -> None:
    """Finished work is kept together, in the order that it was given."""
    goal = _goal()
    tasks = [_task(goal, "a"), _task(goal, "b", "failed")]
    records = [_record(tasks[0]), _record(tasks[1], "failed")]

    entry = ArchiveEntry.create(goal, tasks, records, "all done", "/work/app")

    assert entry.goal == goal
    assert entry.tasks == tuple(tasks)
    assert entry.records == tuple(records)
    assert entry.reason == "all done"
    assert entry.project_path == "/work/app"


def test_an_entry_is_stamped_with_the_time_it_was_archived() -> None:
    """The time is a UTC ISO-8601 string."""
    entry = ArchiveEntry.create(_goal(), [], [], "done")

    assert datetime.fromisoformat(entry.archived_at).tzinfo is not None


def test_a_goal_with_no_tasks_can_be_archived() -> None:
    """There is nothing to move but the goal."""
    entry = ArchiveEntry.create(_goal(), [], [], "never used")

    assert entry.tasks == ()
    assert entry.records == ()


def test_the_project_directory_may_be_unknown() -> None:
    """A project that is not registered has no directory to keep."""
    entry = ArchiveEntry.create(_goal(), [], [], "done")

    assert entry.project_path is None


def test_the_reason_is_trimmed_and_cannot_be_blank() -> None:
    """The archive says why each goal was taken out."""
    goal = _goal()

    assert ArchiveEntry.create(goal, [], [], "  tidy up  ").reason == (
        "tidy up"
    )

    for reason in ("", "   ", "\n"):
        with pytest.raises(ValueError, match="reason cannot be empty"):
            ArchiveEntry.create(goal, [], [], reason)


@pytest.mark.parametrize("status", ["pending", "ready", "running"])
def test_a_task_with_work_in_flight_is_refused(status) -> None:
    """Only finished tasks can be archived, and the error names the task."""
    goal = _goal()
    task = _task(goal, status=status)

    with pytest.raises(ValueError) as caught:
        ArchiveEntry.create(goal, [_task(goal, "ok"), task], [], "done")

    assert str(caught.value) == (
        f"task {task.id} is {status}; only finished tasks can be archived"
    )


def test_a_task_of_another_goal_is_refused() -> None:
    """Every task in the entry belongs to the goal."""
    goal = _goal()
    other = _goal()
    stray = _task(other)

    with pytest.raises(ValueError) as caught:
        ArchiveEntry.create(goal, [stray], [], "done")

    assert str(caught.value) == (
        f"task {stray.id} belongs to goal {other.id}, not {goal.id}"
    )


def test_a_record_of_a_task_that_is_not_in_the_entry_is_refused() -> None:
    """A record cannot be archived without its task."""
    goal = _goal()
    inside = _task(goal)
    outside = _task(goal, "outside")

    with pytest.raises(ValueError) as caught:
        ArchiveEntry.create(goal, [inside], [_record(outside)], "done")

    assert "which is not in the entry" in str(caught.value)


def test_a_record_that_is_still_open_is_refused() -> None:
    """An open record means that the task is not really finished."""
    goal = _goal()
    task = _task(goal)
    open_record = ExecutionRecord.begin(task.id, "coordinator", "noop")

    with pytest.raises(ValueError, match="is still open"):
        ArchiveEntry.create(goal, [task], [open_record], "done")


def test_a_task_or_a_record_listed_twice_is_refused() -> None:
    """Each task and each record appears once."""
    goal = _goal()
    task = _task(goal)

    with pytest.raises(ValueError, match="is listed twice"):
        ArchiveEntry.create(goal, [task, task], [], "done")

    with pytest.raises(ValueError, match="is listed twice"):
        ArchiveEntry.create(
            goal,
            [task],
            [_record(task), _record(task)],
            "done",
        )


def test_an_entry_cannot_be_changed() -> None:
    """The archive is history, so an entry is read-only."""
    entry = ArchiveEntry.create(_goal(), [], [], "done")

    with pytest.raises(AttributeError):
        entry.reason = "something else"


def test_a_blank_archive_time_is_refused() -> None:
    """An entry that was built by hand still needs a time."""
    with pytest.raises(ValueError, match="archive time cannot be empty"):
        ArchiveEntry(
            goal=_goal(),
            tasks=(),
            records=(),
            archived_at="  ",
            reason="done",
        )


def test_lists_given_to_an_entry_are_kept_as_tuples() -> None:
    """An entry stays hashable and compares equal whatever it was given."""
    goal = _goal()
    task = _task(goal)
    record = _record(task)

    entry = ArchiveEntry(
        goal=goal,
        tasks=[task],
        records=[record],
        archived_at="2026-10-30T00:00:00+00:00",
        reason="done",
    )

    assert entry.tasks == (task,)
    assert entry.records == (record,)
    assert isinstance(hash(entry), int)
