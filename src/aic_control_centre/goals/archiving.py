"""Move a finished goal out of the active state and keep its history."""

from __future__ import annotations

from dataclasses import dataclass

from aic_control_centre.execution.records import (
    ExecutionRecord,
    ExecutionRecordRegistry,
)
from aic_control_centre.goals.archive import (
    FINISHED_TASK_STATUSES,
    ArchiveEntry,
    GoalArchive,
)
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import (
    ProjectNameAmbiguousError,
    ProjectNotRegisteredError,
    ProjectRegistry,
)
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


class GoalArchiveError(ValueError):
    """Raised when a goal cannot be archived. Nothing was changed.

    Tasks that are not finished are listed in unfinished, and execution
    records that were left open for finished tasks are listed in
    open_attempts.
    """

    def __init__(
        self,
        message: str,
        unfinished: tuple[Task, ...] = (),
        open_attempts: tuple[ExecutionRecord, ...] = (),
    ) -> None:
        super().__init__(message)
        self.unfinished = tuple(unfinished)
        self.open_attempts = tuple(open_attempts)


@dataclass(frozen=True)
class ArchiveResult:
    """What archiving a goal did.

    resumed is True when an earlier attempt had already written the entry,
    so that only the removal from the active files was finished here, and
    the reason that is kept is the one of the earlier attempt. already_done
    is True when the goal was no longer active and there was nothing to do.
    """

    goal_id: str
    project: str
    project_path: str | None
    tasks: int
    records: int
    reason: str
    resumed: bool = False
    already_done: bool = False


class GoalArchiver:
    """Archive a finished goal, with its tasks and their execution records.

    The entry is written to the archive first. Then the execution records
    are removed from the active file, then the tasks, then the goal. Each
    removal is one atomic write of one file. A crash leaves the work in the
    archive and, in part, still in the active files, and every such state is
    valid for the active files. Archiving the goal again finishes it, and
    the entry that is already in the archive is kept, because it was made
    before anything was removed.
    """

    def __init__(
        self,
        goal_registry: GoalRegistry,
        task_registry: TaskRegistry,
        record_registry: ExecutionRecordRegistry,
        archive: GoalArchive,
        project_registry: ProjectRegistry | None = None,
    ) -> None:
        self.goal_registry = goal_registry
        self.task_registry = task_registry
        self.record_registry = record_registry
        self.archive = archive
        self.project_registry = project_registry

    def _project_path(self, goal: Goal) -> str | None:
        """Return the directory that the registry has for the goal's project.

        A project that is not registered, or whose name more than one
        directory has, gives no directory.
        """
        if self.project_registry is None:
            return None

        try:
            return str(self.project_registry.find_project(goal.project).path)
        except (ProjectNotRegisteredError, ProjectNameAmbiguousError):
            return None

    def archive_goal(self, goal_id: str, reason: str) -> ArchiveResult:
        """Archive a goal, or finish archiving it after a crash."""
        text = reason.strip()

        if not text:
            raise GoalArchiveError("archive reason cannot be empty")

        goal = self.goal_registry.get_goal(goal_id)
        existing = self.archive.get_entry(goal_id)

        if goal is None:
            if existing is None:
                raise GoalArchiveError(f"goal not found: {goal_id}")

            return self._result(existing, already_done=True)

        tasks = self.task_registry.list_tasks_for_goal(goal.id)

        if existing is not None:
            known = {task.id for task in existing.tasks}

            for task in tasks:
                if task.id not in known:
                    raise GoalArchiveError(
                        f"goal {goal.id} is already archived, but task "
                        f"{task.id} is not in the archive"
                    )

            entry = existing
        else:
            entry = self._new_entry(goal, tasks, text)
            self.archive.add_entry(entry)

        self._remove_from_active_files(goal, tasks)

        return self._result(entry, resumed=existing is not None)

    def _new_entry(
        self,
        goal: Goal,
        tasks: list[Task],
        reason: str,
    ) -> ArchiveEntry:
        """Return the entry for a goal that has not been archived."""
        unfinished = tuple(
            task for task in tasks if task.status not in FINISHED_TASK_STATUSES
        )

        if unfinished:
            raise GoalArchiveError(
                f"goal {goal.id} has {len(unfinished)} tasks that are not "
                "finished",
                unfinished,
            )

        task_ids = {task.id for task in tasks}
        records = [
            record
            for record in self.record_registry.list_records()
            if record.task_id in task_ids
        ]
        open_records = tuple(record for record in records if record.is_open)

        if open_records:
            raise GoalArchiveError(
                f"goal {goal.id} cannot be archived: execution record "
                f"{open_records[0].id} is still open",
                open_attempts=open_records,
            )

        try:
            return ArchiveEntry.create(
                goal,
                tasks,
                records,
                reason,
                self._project_path(goal),
            )
        except ValueError as exc:
            raise GoalArchiveError(
                f"goal {goal.id} cannot be archived: {exc}"
            ) from exc

    def _remove_from_active_files(self, goal: Goal, tasks: list[Task]) -> None:
        """Remove the records, then the tasks, then the goal."""
        task_ids = {task.id for task in tasks}
        record_ids = {
            record.id
            for record in self.record_registry.list_records()
            if record.task_id in task_ids
        }

        self.record_registry.remove_records(record_ids)
        self.task_registry.remove_tasks(task_ids)
        self.goal_registry.remove_goal(goal.id)

    def _result(
        self,
        entry: ArchiveEntry,
        resumed: bool = False,
        already_done: bool = False,
    ) -> ArchiveResult:
        return ArchiveResult(
            goal_id=entry.goal.id,
            project=entry.goal.project,
            project_path=entry.project_path,
            tasks=len(entry.tasks),
            records=len(entry.records),
            reason=entry.reason,
            resumed=resumed,
            already_done=already_done,
        )
