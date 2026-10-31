"""Archive of finished goals for AI-Control-Centre.

A finished goal can leave the active state without its history being
destroyed. The goal, its tasks and the execution records of those tasks are
kept together in one entry of an append-only archive file. Nothing in the
archive is read back into the active state.

An entry holds only finished work. A goal with a task that is pending, ready
or running has work in flight, and it is never archived.
"""

from __future__ import annotations

from dataclasses import dataclass

from aic_control_centre.execution.records import ExecutionRecord
from aic_control_centre.goals.model import Goal
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    Task,
    utc_now,
)

FINISHED_TASK_STATUSES = {TASK_STATUS_COMPLETED, TASK_STATUS_FAILED}


@dataclass(frozen=True)
class ArchiveEntry:
    """A finished goal with its tasks and their execution records.

    The project directory is the directory that the registry had for the
    goal's project when the goal was archived, or None when the project was
    not registered. It keeps the history unambiguous if the same project
    name is registered again later for another directory.
    """

    goal: Goal
    tasks: tuple[Task, ...]
    records: tuple[ExecutionRecord, ...]
    archived_at: str
    reason: str
    project_path: str | None = None

    def __post_init__(self) -> None:
        """Reject an entry that is incomplete, inconsistent or not finished."""
        object.__setattr__(self, "tasks", tuple(self.tasks))
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "reason", self.reason.strip())

        if not self.reason:
            raise ValueError("archive reason cannot be empty")

        if not self.archived_at.strip():
            raise ValueError("archive time cannot be empty")

        task_ids: set[str] = set()

        for task in self.tasks:
            if task.id in task_ids:
                raise ValueError(f"task {task.id} is listed twice")

            task_ids.add(task.id)

            if task.goal_id != self.goal.id:
                raise ValueError(
                    f"task {task.id} belongs to goal {task.goal_id}, "
                    f"not {self.goal.id}"
                )

            if task.status not in FINISHED_TASK_STATUSES:
                raise ValueError(
                    f"task {task.id} is {task.status}; only finished tasks "
                    "can be archived"
                )

        record_ids: set[str] = set()

        for record in self.records:
            if record.id in record_ids:
                raise ValueError(
                    f"execution record {record.id} is listed twice"
                )

            record_ids.add(record.id)

            if record.task_id not in task_ids:
                raise ValueError(
                    f"execution record {record.id} belongs to task "
                    f"{record.task_id}, which is not in the entry"
                )

            if record.is_open:
                raise ValueError(
                    f"execution record {record.id} is still open"
                )

    @classmethod
    def create(
        cls,
        goal: Goal,
        tasks: list[Task] | tuple[Task, ...],
        records: list[ExecutionRecord] | tuple[ExecutionRecord, ...],
        reason: str,
        project_path: str | None = None,
    ) -> ArchiveEntry:
        """Return a new entry that is archived now."""
        return cls(
            goal=goal,
            tasks=tuple(tasks),
            records=tuple(records),
            archived_at=utc_now(),
            reason=reason,
            project_path=project_path,
        )
