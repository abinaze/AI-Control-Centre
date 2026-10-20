"""Report how long tasks have been running."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from aic_control_centre.execution.records import (
    ExecutionRecord,
    ExecutionRecordRegistry,
)
from aic_control_centre.tasks.model import TASK_STATUS_RUNNING
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.timestamps import read_time

PROBLEM_FUTURE = "future"
PROBLEM_UNREADABLE = "unreadable"

UNKNOWN_ROUTE = "unknown (before records existed)"

DURATION_HELP = "a whole number followed by s, m, h or d, for example 30m"

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION = re.compile(r"([0-9]+)([smhd])")


@dataclass(frozen=True)
class RunningTask:
    """Describe one running task and how long it has been running.

    The elapsed time is advisory. It says how long, and never whether
    anything is still running the task. It is None when the start time
    cannot be read. The problem is None, or says why the time is not
    usable as it stands.
    """

    task_id: str
    goal_id: str
    title: str
    route: str
    since: str
    estimated: bool
    elapsed: timedelta | None
    problem: str | None


def parse_duration(text: str) -> timedelta:
    """Read a duration such as 30s, 15m, 2h or 1d."""
    match = _DURATION.fullmatch(text.strip())

    if match is None:
        raise ValueError(f"cannot read duration {text!r}; use {DURATION_HELP}")

    amount = int(match.group(1))

    if amount < 1:
        raise ValueError("duration must be greater than zero")

    try:
        return timedelta(seconds=amount * _UNIT_SECONDS[match.group(2)])
    except OverflowError as exc:
        raise ValueError("duration is too large") from exc


def format_elapsed(elapsed: timedelta) -> str:
    """Describe an elapsed time as 42s, 5m, 3h 12m or 2d 6h."""
    seconds = int(elapsed.total_seconds())

    if seconds < 60:
        return f"{seconds}s"

    minutes = seconds // 60

    if minutes < 60:
        return f"{minutes}m"

    hours, minutes = divmod(minutes, 60)

    if hours < 24:
        return f"{hours}h {minutes}m"

    days, hours = divmod(hours, 24)

    return f"{days}d {hours}h"


def _route(record: ExecutionRecord) -> str:
    """Describe how an attempt was started."""
    if record.target:
        return f"{record.source} ({record.target})"

    return record.source


def _sort_key(row: RunningTask) -> tuple[int, float]:
    """Put unreadable times first, then the longest running first."""
    unreadable = 0 if row.problem == PROBLEM_UNREADABLE else 1
    seconds = 0.0 if row.elapsed is None else row.elapsed.total_seconds()

    return (unreadable, -seconds)


def describe_running_tasks(
    task_registry: TaskRegistry,
    record_registry: ExecutionRecordRegistry,
    now: datetime,
) -> list[RunningTask]:
    """Return the running tasks, the longest running first.

    A task is timed from its latest open attempt. A running task with no
    open attempt started before records existed, so it is timed from the
    last update of the task, which is when it began running, and the
    time is marked as an estimate. The clock is given by the caller and
    must have a time zone. Nothing is written.
    """
    open_by_task: dict[str, ExecutionRecord] = {}

    for record in record_registry.list_records():
        if record.is_open:
            open_by_task[record.task_id] = record

    rows: list[RunningTask] = []

    for task in task_registry.list_tasks():
        if task.status != TASK_STATUS_RUNNING:
            continue

        attempt = open_by_task.get(task.id)

        if attempt is None:
            raw, estimated, route = task.updated_at, True, UNKNOWN_ROUTE
        else:
            raw, estimated, route = attempt.started_at, False, _route(attempt)

        moment = read_time(raw)
        elapsed: timedelta | None = None
        problem: str | None = None

        if moment is None:
            since = str(raw)
            problem = PROBLEM_UNREADABLE
        else:
            since = moment.isoformat(timespec="seconds")
            elapsed = now - moment

            if elapsed < timedelta(0):
                elapsed = timedelta(0)
                problem = PROBLEM_FUTURE

        rows.append(
            RunningTask(
                task_id=task.id,
                goal_id=task.goal_id,
                title=task.title,
                route=route,
                since=since,
                estimated=estimated,
                elapsed=elapsed,
                problem=problem,
            )
        )

    rows.sort(key=_sort_key)

    return rows


def filter_older_than(
    rows: list[RunningTask],
    threshold: timedelta,
) -> list[RunningTask]:
    """Keep the tasks that have run for at least the threshold.

    A task whose start time cannot be read is kept, so that bad data
    never hides it. A task whose start time is in the future is not kept.
    """
    return [
        row
        for row in rows
        if row.problem == PROBLEM_UNREADABLE
        or (row.problem is None and row.elapsed >= threshold)
    ]
