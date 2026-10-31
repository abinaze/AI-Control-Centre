"""Archive of finished goals for AI-Control-Centre.

A finished goal can leave the active state without its history being
destroyed. The goal, its tasks and the execution records of those tasks are
kept together in one entry of an append-only archive file. Nothing in the
archive is read back into the active state.

An entry holds only finished work. A goal with a task that is pending, ready
or running has work in flight, and it is never archived.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from aic_control_centre.execution.records import ExecutionRecord
from aic_control_centre.goals.model import Goal
from aic_control_centre.storage import (
    StateFileError,
    read_state_items_or_empty,
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    Task,
    utc_now,
)

FINISHED_TASK_STATUSES = {TASK_STATUS_COMPLETED, TASK_STATUS_FAILED}

ARCHIVE_FILE_NAME = "archive.json"
ARCHIVE_COLLECTION = "archived"


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


def _entry_to_item(entry: ArchiveEntry) -> dict[str, Any]:
    """Return the JSON form of an entry."""
    return {
        "archived_at": entry.archived_at,
        "reason": entry.reason,
        "project_path": entry.project_path,
        "goal": asdict(entry.goal),
        "tasks": [asdict(task) for task in entry.tasks],
        "records": [asdict(record) for record in entry.records],
    }


def _item_to_entry(item: Any) -> ArchiveEntry:
    """Return the entry that a JSON item holds."""
    goal = item["goal"]

    return ArchiveEntry(
        goal=Goal(
            id=goal["id"],
            description=goal["description"],
            project=goal["project"],
            status=goal["status"],
            created_at=goal["created_at"],
            updated_at=goal["updated_at"],
        ),
        tasks=tuple(
            Task(
                id=task["id"],
                goal_id=task["goal_id"],
                title=task["title"],
                description=task["description"],
                status=task["status"],
                created_at=task["created_at"],
                updated_at=task["updated_at"],
            )
            for task in item["tasks"]
        ),
        records=tuple(
            ExecutionRecord(
                id=record["id"],
                task_id=record["task_id"],
                source=record["source"],
                target=record["target"],
                started_at=record["started_at"],
                ended_at=record["ended_at"],
                ended_as=record["ended_as"],
                reason=record["reason"],
            )
            for record in item["records"]
        ),
        archived_at=item["archived_at"],
        reason=item["reason"],
        project_path=item["project_path"],
    )


class GoalArchive:
    """Manage the append-only file of archived goals.

    The file is read with the reader that tells a file that is not there
    from a file that cannot be read, so a file that cannot be read for a
    moment is an error and is never overwritten as if it were empty.
    """

    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path

    @classmethod
    def beside(cls, task_registry_path: Path) -> GoalArchive:
        """Return the archive stored next to a task registry file."""
        return cls(task_registry_path.with_name(ARCHIVE_FILE_NAME))

    def _load(self) -> list[ArchiveEntry]:
        """Load the archived entries from disk."""
        data = read_state_items_or_empty(
            self.registry_path,
            ARCHIVE_COLLECTION,
        )

        try:
            return [_item_to_entry(item) for item in data]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise StateFileError(
                f"{self.registry_path} has an invalid archive entry: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def _save(self, entries: list[ArchiveEntry]) -> None:
        """Persist the archived entries to disk."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        write_text_atomic(
            self.registry_path,
            serialize_state_items(
                ARCHIVE_COLLECTION,
                [_entry_to_item(entry) for entry in entries],
            ),
        )

    def list_entries(self) -> list[ArchiveEntry]:
        """Return every archived entry, oldest first."""
        return self._load()

    def get_entry(self, goal_id: str) -> ArchiveEntry | None:
        """Return the entry of a goal, or None when it is not archived."""
        for entry in self._load():
            if entry.goal.id == goal_id:
                return entry

        return None

    def has_goal(self, goal_id: str) -> bool:
        """Return whether a goal is in the archive."""
        return self.get_entry(goal_id) is not None

    def add_entry(self, entry: ArchiveEntry) -> bool:
        """Append an entry, unless its goal is already archived.

        Returns True when the entry was written. A goal that is already in
        the archive is not written twice, and the entry that is there is
        kept: it was made before anything was removed from the active
        files, so it is the complete one. That is what makes archiving safe
        to run again after a crash.
        """
        entries = self._load()

        for existing in entries:
            if existing.goal.id == entry.goal.id:
                return False

        entries.append(entry)
        self._save(entries)

        return True
