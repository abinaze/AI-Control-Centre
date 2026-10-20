"""Tests for the running task report."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from aic_control_centre.execution.records import (
    ExecutionRecord,
    ExecutionRecordRegistry,
)
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.tasks.running import (
    PROBLEM_FUTURE,
    PROBLEM_UNREADABLE,
    UNKNOWN_ROUTE,
    describe_running_tasks,
    filter_older_than,
    format_elapsed,
    parse_duration,
)

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
EARLIER = "2026-10-19T09:00:00+00:00"


def _task(task_id, status="running", updated_at=EARLIER):
    return Task(
        id=task_id,
        goal_id="goal-1",
        title=f"title {task_id}",
        description="",
        status=status,
        created_at="2026-10-01T00:00:00+00:00",
        updated_at=updated_at,
    )


def _record(
    record_id,
    task_id,
    started_at=EARLIER,
    source="cli",
    target=None,
    ended_as=None,
):
    ended_at = None if ended_as is None else "2026-10-19T11:00:00+00:00"

    return ExecutionRecord(
        id=record_id,
        task_id=task_id,
        source=source,
        target=target,
        started_at=started_at,
        ended_at=ended_at,
        ended_as=ended_as,
        reason="",
    )


def _registries(tmp_path, tasks, records=()):
    write_text_atomic(
        tmp_path / "tasks.json",
        serialize_state_items("tasks", [asdict(task) for task in tasks]),
    )

    if records:
        write_text_atomic(
            tmp_path / "executions.json",
            serialize_state_items(
                "executions",
                [asdict(record) for record in records],
            ),
        )

    return (
        TaskRegistry(tmp_path / "tasks.json"),
        ExecutionRecordRegistry(tmp_path / "executions.json"),
    )


def _describe(tmp_path, tasks, records=()):
    task_registry, record_registry = _registries(tmp_path, tasks, records)

    return describe_running_tasks(task_registry, record_registry, NOW)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("30s", 30),
        ("15m", 900),
        ("2h", 7200),
        ("1d", 86400),
        (" 5m ", 300),
        ("007s", 7),
    ],
)
def test_parse_duration_reads_a_number_and_a_unit(text, seconds) -> None:
    """Seconds, minutes, hours and days are understood."""
    assert parse_duration(text) == timedelta(seconds=seconds)


@pytest.mark.parametrize(
    "text",
    ["", "m", "5", "5w", "-5m", "1.5h", "1 h", "5M", "m5", "10m30s"],
)
def test_parse_duration_refuses_anything_else(text) -> None:
    """A duration is a whole number and one lower-case unit."""
    with pytest.raises(ValueError, match="for example 30m"):
        parse_duration(text)


def test_parse_duration_refuses_zero() -> None:
    """A limit of nothing is not a limit."""
    with pytest.raises(ValueError, match="greater than zero"):
        parse_duration("0m")


def test_parse_duration_refuses_a_number_that_is_too_large() -> None:
    """An absurd number is an error and not a crash."""
    with pytest.raises(ValueError, match="too large"):
        parse_duration("9" * 30 + "d")


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0s"),
        (42, "42s"),
        (60, "1m"),
        (3599, "59m"),
        (3600, "1h 0m"),
        (3 * 3600 + 12 * 60, "3h 12m"),
        (86399, "23h 59m"),
        (86400, "1d 0h"),
        (2 * 86400 + 6 * 3600 + 59, "2d 6h"),
    ],
)
def test_format_elapsed(seconds, text) -> None:
    """The two largest units that matter are shown."""
    assert format_elapsed(timedelta(seconds=seconds)) == text


def test_only_running_tasks_are_listed(tmp_path) -> None:
    """A task in any other status is not."""
    tasks = [
        _task("pending", status="pending"),
        _task("ready", status="ready"),
        _task("running"),
        _task("completed", status="completed"),
        _task("failed", status="failed"),
    ]

    rows = _describe(tmp_path, tasks)

    assert [row.task_id for row in rows] == ["running"]


def test_nothing_running_gives_an_empty_report(tmp_path) -> None:
    """With no running task there are no rows."""
    assert _describe(tmp_path, [_task("done", status="completed")]) == []


def test_a_task_is_timed_from_its_open_attempt(tmp_path) -> None:
    """The attempt holds the exact start time and the route."""
    rows = _describe(
        tmp_path,
        [_task("t1", updated_at="2026-10-19T11:59:00+00:00")],
        [_record("r1", "t1", started_at="2026-10-19T08:48:00+00:00")],
    )

    [row] = rows

    assert row.elapsed == timedelta(hours=3, minutes=12)
    assert row.since == "2026-10-19T08:48:00+00:00"
    assert row.estimated is False
    assert row.problem is None
    assert (row.title, row.goal_id) == ("title t1", "goal-1")


def test_the_latest_open_attempt_is_used_and_closed_ones_are_not(
    tmp_path,
) -> None:
    """Older closed attempts do not change the time."""
    records = [
        _record(
            "r1",
            "t1",
            started_at="2026-10-17T00:00:00+00:00",
            ended_as="requeued",
        ),
        _record("r2", "t1", started_at="2026-10-19T11:00:00+00:00"),
    ]

    [row] = _describe(tmp_path, [_task("t1")], records)

    assert row.elapsed == timedelta(hours=1)


def test_an_open_attempt_is_used_even_when_a_closed_record_follows_it(
    tmp_path,
) -> None:
    """Only open records count, wherever they are in the file."""
    records = [
        _record("r1", "t1", started_at="2026-10-19T11:00:00+00:00"),
        _record(
            "r2",
            "t1",
            started_at="2026-10-19T11:30:00+00:00",
            ended_as="requeued",
        ),
    ]

    [row] = _describe(tmp_path, [_task("t1")], records)

    assert row.estimated is False
    assert row.elapsed == timedelta(hours=1)


def test_a_task_with_no_open_attempt_is_timed_from_its_last_update(
    tmp_path,
) -> None:
    """A task from before records existed is timed by an estimate."""
    [row] = _describe(
        tmp_path,
        [_task("t1", updated_at="2026-10-16T06:00:00+00:00")],
    )

    assert row.elapsed == timedelta(days=3, hours=6)
    assert row.estimated is True
    assert row.route == UNKNOWN_ROUTE
    assert row.problem is None


def test_a_task_whose_only_attempts_are_closed_is_estimated(
    tmp_path,
) -> None:
    """Closed attempts say nothing about the run that is going on now."""
    records = [
        _record("r1", "t1", started_at="2026-10-01T00:00:00+00:00",
                ended_as="requeued"),
    ]

    [row] = _describe(tmp_path, [_task("t1")], records)

    assert row.estimated is True
    assert row.elapsed == timedelta(hours=3)


def test_the_route_shows_how_the_attempt_started(tmp_path) -> None:
    """A CLI attempt and a coordinator attempt are told apart."""
    tasks = [_task("a"), _task("b")]
    records = [
        _record("r1", "a", source="cli"),
        _record("r2", "b", source="coordinator", target="process"),
    ]

    rows = {row.task_id: row for row in _describe(tmp_path, tasks, records)}

    assert rows["a"].route == "cli"
    assert rows["b"].route == "coordinator (process)"


def test_an_open_attempt_for_a_task_that_is_not_running_is_ignored(
    tmp_path,
) -> None:
    """An attempt left open for a finished task is not listed."""
    tasks = [_task("t1", status="completed")]

    assert _describe(tmp_path, tasks, [_record("r1", "t1")]) == []


def test_the_longest_running_task_comes_first(tmp_path) -> None:
    """Oldest first, whatever the order in the file."""
    tasks = [_task("new"), _task("old"), _task("middle")]
    records = [
        _record("r1", "new", started_at="2026-10-19T11:30:00+00:00"),
        _record("r2", "old", started_at="2026-10-17T00:00:00+00:00"),
        _record("r3", "middle", started_at="2026-10-19T06:00:00+00:00"),
    ]

    rows = _describe(tmp_path, tasks, records)

    assert [row.task_id for row in rows] == ["old", "middle", "new"]


def test_a_start_time_in_the_future_is_flagged_and_counts_as_zero(
    tmp_path,
) -> None:
    """A clock that moved back is shown as it is, not hidden."""
    [row] = _describe(
        tmp_path,
        [_task("t1")],
        [_record("r1", "t1", started_at="2026-10-19T15:00:00+00:00")],
    )

    assert row.problem == PROBLEM_FUTURE
    assert row.elapsed == timedelta(0)


@pytest.mark.parametrize(
    "started_at",
    ["garbage", "", "2026-10-19", "2026-10-19T09:00:00"],
)
def test_a_start_time_that_cannot_be_used_is_flagged(
    tmp_path,
    started_at,
) -> None:
    """Text, a bare date or a time with no offset cannot be compared."""
    [row] = _describe(
        tmp_path,
        [_task("t1")],
        [_record("r1", "t1", started_at=started_at)],
    )

    assert row.problem == PROBLEM_UNREADABLE
    assert row.elapsed is None
    assert row.since == started_at


def test_an_unreadable_task_time_is_flagged_for_an_estimate(
    tmp_path,
) -> None:
    """The fallback time is checked in the same way."""
    [row] = _describe(tmp_path, [_task("t1", updated_at="not a time")])

    assert row.estimated is True
    assert row.problem == PROBLEM_UNREADABLE


def test_a_time_with_another_offset_is_read_as_utc(tmp_path) -> None:
    """A stored offset is honoured when the elapsed time is worked out."""
    [row] = _describe(
        tmp_path,
        [_task("t1")],
        [_record("r1", "t1", started_at="2026-10-19T14:00:00+05:00")],
    )

    assert row.since == "2026-10-19T09:00:00+00:00"
    assert row.elapsed == timedelta(hours=3)


def test_unreadable_times_come_first_and_future_ones_last(tmp_path) -> None:
    """Bad data is put where it will be seen."""
    tasks = [_task("ok"), _task("future"), _task("bad")]
    records = [
        _record("r1", "ok", started_at="2026-10-19T10:00:00+00:00"),
        _record("r2", "future", started_at="2026-10-19T18:00:00+00:00"),
        _record("r3", "bad", started_at="garbage"),
    ]

    rows = _describe(tmp_path, tasks, records)

    assert [row.task_id for row in rows] == ["bad", "ok", "future"]


def test_the_elapsed_time_comes_from_the_clock_that_is_given(
    tmp_path,
) -> None:
    """The report does not read the real time."""
    task_registry, record_registry = _registries(
        tmp_path,
        [_task("t1")],
        [_record("r1", "t1", started_at="2026-10-19T11:00:00+00:00")],
    )

    later = NOW + timedelta(hours=5)

    [row] = describe_running_tasks(task_registry, record_registry, later)

    assert row.elapsed == timedelta(hours=6)


def test_describing_never_writes(tmp_path) -> None:
    """Both state files are identical afterwards."""
    _describe(
        tmp_path,
        [_task("t1"), _task("t2")],
        [_record("r1", "t1")],
    )
    before = {
        name: (tmp_path / name).read_bytes()
        for name in ("tasks.json", "executions.json")
    }

    task_registry = TaskRegistry(tmp_path / "tasks.json")
    record_registry = ExecutionRecordRegistry(tmp_path / "executions.json")
    describe_running_tasks(task_registry, record_registry, NOW)

    after = {name: (tmp_path / name).read_bytes() for name in before}

    assert after == before


def test_older_than_keeps_tasks_at_or_over_the_limit(tmp_path) -> None:
    """The limit itself counts as long enough."""
    tasks = [_task("old"), _task("exact"), _task("new")]
    records = [
        _record("r1", "old", started_at="2026-10-19T08:00:00+00:00"),
        _record("r2", "exact", started_at="2026-10-19T10:00:00+00:00"),
        _record("r3", "new", started_at="2026-10-19T10:00:01+00:00"),
    ]
    rows = _describe(tmp_path, tasks, records)

    kept = filter_older_than(rows, timedelta(hours=2))

    assert [row.task_id for row in kept] == ["old", "exact"]


def test_older_than_keeps_unreadable_and_drops_future_times(
    tmp_path,
) -> None:
    """Bad data is never hidden, and a future start is never long."""
    tasks = [_task("bad"), _task("future"), _task("old")]
    records = [
        _record("r1", "bad", started_at="garbage"),
        _record("r2", "future", started_at="2026-10-19T20:00:00+00:00"),
        _record("r3", "old", started_at="2026-10-18T00:00:00+00:00"),
    ]
    rows = _describe(tmp_path, tasks, records)

    kept = filter_older_than(rows, timedelta(minutes=1))

    assert [row.task_id for row in kept] == ["bad", "old"]
