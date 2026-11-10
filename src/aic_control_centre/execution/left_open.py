"""Close an attempt that was left open for a task that is final.

When a task is completed or failed, the task moves first and its attempt
record is closed after it. If the records file cannot be written at that
moment, the task is final and its attempt stays open, and nothing starts
a final task again, so nothing closes the attempt. This module is the
narrow way out: it closes that one attempt, with the outcome that the task
already has, and with a reason that a person gave.

It refuses every other state and writes nothing for a refusal. In
particular it never calls close_attempt for a task that has no open
attempt, because that would add a closed record that has no start.

The caller holds the state lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aic_control_centre.execution.records import (
    ExecutionRecord,
    ExecutionRecordRegistry,
)
from aic_control_centre.execution.run_lock import (
    OWNER_ALIVE,
    OWNER_GONE,
    OWNER_UNKNOWN,
    remove_run_lock_file,
)
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
)
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.tasks.running import OWNER_ENDED, owner_of_attempt

# The stored reason begins with this, so that aic task history shows that
# the normal lifecycle did not close the attempt.
LEFT_OPEN_REASON_PREFIX = "closed afterwards: "


class LeftOpenRefused(ValueError):
    """The attempt was not closed. The message says why and what to do."""


@dataclass(frozen=True)
class ClosedLeftOpen:
    """The attempt that was closed, and what was known of its owner."""

    record: ExecutionRecord
    owner: str


def close_left_open_attempt(
    task_registry: TaskRegistry,
    record_registry: ExecutionRecordRegistry,
    task_id: str,
    reason: str,
    data_dir: Path | None = None,
) -> ClosedLeftOpen:
    """Close the one open attempt of a task that is completed or failed.

    The outcome of the attempt is the status of the task, the reason is
    the given one with LEFT_OPEN_REASON_PREFIX in front of it, and the
    time is the time of this call. When a data directory is given, the
    owner of the attempt is asked: a run that is alive is refused, an
    attempt that was closed while it was asked is refused as having no
    open attempt, and the lock file of a run that is gone is removed
    after the attempt is closed.

    Raises LeftOpenRefused, and writes nothing, for a blank reason, an
    unknown task, a task that is not completed or failed, a task with no
    open attempt, a task with more than one, and a run that is alive.
    """
    if not reason.strip():
        raise LeftOpenRefused("a reason is required to close an attempt.")

    task = task_registry.get_task(task_id.strip())

    if task is None:
        raise LeftOpenRefused(f"task not found: {task_id}")

    if task.status == TASK_STATUS_RUNNING:
        raise LeftOpenRefused(
            f"task {task.id} is running; finish it with aic task complete, "
            "aic task fail or aic task requeue."
        )

    if task.status not in (TASK_STATUS_COMPLETED, TASK_STATUS_FAILED):
        raise LeftOpenRefused(
            f"task {task.id} is {task.status}, so it is not final. The "
            "next aic task start closes a left-over attempt as abandoned."
        )

    open_attempts = [
        record
        for record in record_registry.list_attempts(task.id)
        if record.is_open
    ]

    if not open_attempts:
        raise LeftOpenRefused(f"task {task.id} has no open attempt.")

    if len(open_attempts) > 1:
        raise LeftOpenRefused(
            f"task {task.id} has {len(open_attempts)} open attempts. The "
            "lifecycle cannot make that state, so it came from a hand "
            "edit, and it has to be put right by hand."
        )

    attempt = open_attempts[0]
    owner = OWNER_UNKNOWN

    if data_dir is not None:
        owner = owner_of_attempt(data_dir, record_registry, attempt)

    if owner == OWNER_ENDED:
        # The attempt was closed while the owner was asked. Closing it again
        # would add a record that has no start.
        raise LeftOpenRefused(f"task {task.id} has no open attempt.")

    if owner == OWNER_ALIVE:
        raise LeftOpenRefused(
            f"the run of task {task.id} is still alive: the aic process "
            "that runs it holds its lock. Wait for it to end, or stop "
            "that process, and then close the attempt."
        )

    closed = record_registry.close_attempt(
        task_id=task.id,
        ended_as=task.status,
        reason=LEFT_OPEN_REASON_PREFIX + reason.strip(),
    )

    if owner == OWNER_GONE and data_dir is not None:
        remove_run_lock_file(data_dir, attempt.id)

    return ClosedLeftOpen(record=closed, owner=owner)
