"""Execution attempt records for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from uuid import uuid4

from aic_control_centre.storage import (
    StateFileError,
    read_state_items,
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.model import utc_now


EXECUTION_RECORDS_FILE_NAME = "executions.json"

EXECUTION_SOURCE_CLI = "cli"
EXECUTION_SOURCE_COORDINATOR = "coordinator"

KNOWN_EXECUTION_SOURCES = {
    EXECUTION_SOURCE_CLI,
    EXECUTION_SOURCE_COORDINATOR,
}

ENDED_AS_COMPLETED = "completed"
ENDED_AS_FAILED = "failed"
ENDED_AS_REQUEUED = "requeued"
ENDED_AS_ABANDONED = "abandoned"

# A caller may close an attempt with any of these. Only the registry
# marks an attempt abandoned, when it finds one left open.
CLOSING_ENDED_AS = {
    ENDED_AS_COMPLETED,
    ENDED_AS_FAILED,
    ENDED_AS_REQUEUED,
}

KNOWN_ENDED_AS = CLOSING_ENDED_AS | {ENDED_AS_ABANDONED}

ABANDONED_REASON = "attempt was still open when the task was started again"


@dataclass(frozen=True)
class ExecutionRecord:
    """Describe one attempt to run a task.

    An attempt is open until it ends. A closed record with no start time
    is written for a task that was already running before records
    existed, so that its ending is still recorded.
    """

    id: str
    task_id: str
    source: str
    target: str | None
    started_at: str | None
    ended_at: str | None
    ended_as: str | None
    reason: str

    def __post_init__(self) -> None:
        """Reject incomplete or inconsistent execution records."""
        if not self.id.strip():
            raise ValueError("execution record ID cannot be empty")

        if not self.task_id.strip():
            raise ValueError("task ID cannot be empty")

        if self.source not in KNOWN_EXECUTION_SOURCES:
            raise ValueError(f"unknown execution source: {self.source}")

        if self.ended_as is not None and self.ended_as not in KNOWN_ENDED_AS:
            raise ValueError(f"unknown execution end: {self.ended_as}")

        if (self.ended_at is None) != (self.ended_as is None):
            raise ValueError("ended_at and ended_as must be set together")

        if self.started_at is None and self.ended_as is None:
            raise ValueError("an open execution record needs a start time")

    @property
    def is_open(self) -> bool:
        """Return True while the attempt has not ended."""
        return self.ended_as is None

    @classmethod
    def begin(
        cls,
        task_id: str,
        source: str,
        target: str | None = None,
    ) -> ExecutionRecord:
        """Return a new open record that starts now."""
        return cls(
            id=str(uuid4()),
            task_id=task_id,
            source=source,
            target=target,
            started_at=utc_now(),
            ended_at=None,
            ended_as=None,
            reason="",
        )


def _last_open_index(
    records: list[ExecutionRecord],
    task_id: str,
) -> int | None:
    """Return the position of the latest open record for a task."""
    for index in range(len(records) - 1, -1, -1):
        record = records[index]

        if record.task_id == task_id and record.is_open:
            return index

    return None


class ExecutionRecordRegistry:
    """Manage the persistent local execution record registry.

    The file path is always given explicitly, so a registry cannot point
    at the real data directory by accident. Use beside() to place the
    file next to a task registry's file.
    """

    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path

    @classmethod
    def beside(cls, task_registry_path: Path) -> ExecutionRecordRegistry:
        """Return the registry stored next to a task registry file."""
        return cls(task_registry_path.with_name(EXECUTION_RECORDS_FILE_NAME))

    def _load(self) -> list[ExecutionRecord]:
        """Load execution records from disk."""
        if not self.registry_path.exists():
            return []

        data = read_state_items(self.registry_path, "executions")

        try:
            return [
                ExecutionRecord(
                    id=item["id"],
                    task_id=item["task_id"],
                    source=item["source"],
                    target=item["target"],
                    started_at=item["started_at"],
                    ended_at=item["ended_at"],
                    ended_as=item["ended_as"],
                    reason=item["reason"],
                )
                for item in data
            ]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise StateFileError(
                f"{self.registry_path} has an invalid execution record: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def _save(self, records: list[ExecutionRecord]) -> None:
        """Persist execution records to disk."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        write_text_atomic(
            self.registry_path,
            serialize_state_items(
                "executions",
                [asdict(record) for record in records],
            ),
        )

    def list_records(self) -> list[ExecutionRecord]:
        """Return every record, oldest first."""
        return self._load()

    def list_attempts(self, task_id: str) -> list[ExecutionRecord]:
        """Return the records for one task, oldest first."""
        return [
            record
            for record in self._load()
            if record.task_id == task_id
        ]

    def get_open_attempt(self, task_id: str) -> ExecutionRecord | None:
        """Return the latest open record for a task, if there is one."""
        for record in reversed(self.list_attempts(task_id)):
            if record.is_open:
                return record

        return None

    def open_attempt(
        self,
        task_id: str,
        source: str,
        target: str | None = None,
    ) -> ExecutionRecord:
        """Open a new attempt for a task.

        A task is ready when it is started, so an open record that still
        exists for it was left behind by a crash or by a route that did
        not record. It is closed as abandoned. Closing it and opening the
        new record are saved together in one write.
        """
        new_record = ExecutionRecord.begin(task_id, source, target)
        now = utc_now()

        records = [
            replace(
                record,
                ended_at=now,
                ended_as=ENDED_AS_ABANDONED,
                reason=ABANDONED_REASON,
            )
            if record.task_id == task_id and record.is_open
            else record
            for record in self._load()
        ]
        records.append(new_record)

        self._save(records)

        return new_record

    def close_attempt(
        self,
        task_id: str,
        ended_as: str,
        reason: str = "",
        source: str = EXECUTION_SOURCE_CLI,
    ) -> ExecutionRecord:
        """Close the latest open attempt for a task.

        When the task has no open attempt, it was already running before
        records existed. A closed record with no start time is written
        instead, using the given source for the route that is closing it.
        """
        if ended_as not in CLOSING_ENDED_AS:
            raise ValueError(f"cannot close an attempt as {ended_as}")

        records = self._load()
        now = utc_now()
        text = reason.strip()
        index = _last_open_index(records, task_id)

        if index is None:
            closed = ExecutionRecord(
                id=str(uuid4()),
                task_id=task_id,
                source=source,
                target=None,
                started_at=None,
                ended_at=now,
                ended_as=ended_as,
                reason=text,
            )
            records.append(closed)
        else:
            closed = replace(
                records[index],
                ended_at=now,
                ended_as=ended_as,
                reason=text,
            )
            records[index] = closed

        self._save(records)

        return closed
