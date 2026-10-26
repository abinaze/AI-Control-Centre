"""Validation for persisted goal and task state."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.goals.model import (
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    KNOWN_GOAL_STATUSES,
    Goal,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.orchestration.goal_tasks import derive_goal_status
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.directory import (
    MISSING,
    NOT_A_DIRECTORY,
    directory_problem,
)
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_PENDING,
    TASK_STATUS_READY,
    TASK_STATUS_RUNNING,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.timestamps import read_time


KNOWN_TASK_STATUSES = {
    TASK_STATUS_PENDING,
    TASK_STATUS_READY,
    TASK_STATUS_RUNNING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
}


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating persisted goal/task state."""

    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        """Return whether validation completed without errors."""
        return not self.errors


class GoalTaskValidator:
    """Validate persisted goal/task relationships without modifying state.

    Goal project references are checked only when a project registry is
    given; without one, project names are not checked. Execution records
    are checked only when a record registry is given. Grants are checked
    only when a permission registry is given. A grant that is still active
    must name a registered project, when a project registry is given, and
    a known target, when the targets are given. A revoked grant is history
    and is left alone, apart from its ID and its times. The times of
    goals and tasks, and of the records and grants that are checked, must
    be readable as ISO 8601 text with an offset. A project name that is
    used by more than one registered directory is reported, when a project
    registry is given. So is a registered directory that does not exist or
    is not a directory.
    """

    def __init__(
        self,
        goal_registry: GoalRegistry | None = None,
        task_registry: TaskRegistry | None = None,
        project_registry: ProjectRegistry | None = None,
        record_registry: ExecutionRecordRegistry | None = None,
        permission_registry: PermissionRegistry | None = None,
        known_targets: Iterable[str] | None = None,
    ) -> None:
        self.goal_registry = goal_registry or GoalRegistry()
        self.task_registry = task_registry or TaskRegistry()
        self.project_registry = project_registry
        self.record_registry = record_registry
        self.permission_registry = permission_registry
        self.known_targets = (
            None if known_targets is None else frozenset(known_targets)
        )

    def _registered_project_names(self) -> set[str] | None:
        """Return registered project names, or None when not checking."""
        if self.project_registry is None:
            return None

        return {
            project.name
            for project in self.project_registry.list_projects()
        }

    def _project_name_errors(self) -> list[str]:
        """Return an error for each name that more than one directory has.

        Goals and permissions identify a project by its name, so a name
        that belongs to two directories does not say which one is meant.
        The check applies only when a project registry is given.
        """
        if self.project_registry is None:
            return []

        paths_by_name: dict[str, list[str]] = {}

        for project in self.project_registry.list_projects():
            paths_by_name.setdefault(project.name, []).append(
                str(project.path)
            )

        return [
            "Project name is used by more than one directory: "
            f"{name} ({', '.join(paths)})"
            for name, paths in paths_by_name.items()
            if len(paths) > 1
        ]

    def _project_directory_errors(self) -> list[str]:
        """Return an error for each project whose directory is not usable.

        The directory is only looked at, and never created. The check
        applies only when a project registry is given.
        """
        if self.project_registry is None:
            return []

        errors: list[str] = []

        for project in self.project_registry.list_projects():
            problem = directory_problem(project.path)

            if problem is None:
                continue

            kind, detail = problem

            if kind == MISSING:
                errors.append(
                    "Project directory does not exist: "
                    f"{project.name} ({project.path})"
                )
            elif kind == NOT_A_DIRECTORY:
                errors.append(
                    "Project path is not a directory: "
                    f"{project.name} ({project.path})"
                )
            else:
                errors.append(
                    "Project directory cannot be read: "
                    f"{project.name} ({project.path}); {detail}"
                )

        return errors

    def _record_errors(self, tasks: list[Task]) -> list[str]:
        """Return the errors found in the execution records.

        Only open records are compared with task status. A running task
        with no record is accepted, because a task started before
        records existed has none.
        """
        if self.record_registry is None:
            return []

        status_by_task = {task.id: task.status for task in tasks}
        errors: list[str] = []
        record_ids: set[str] = set()
        open_counts: dict[str, int] = {}

        for record in self.record_registry.list_records():
            if record.id in record_ids:
                errors.append(f"Duplicate execution record ID: {record.id}")
            else:
                record_ids.add(record.id)

            status = status_by_task.get(record.task_id)

            if status is None:
                errors.append(
                    f"Execution record {record.id} references missing "
                    f"task: {record.task_id}"
                )
                continue

            if not record.is_open:
                continue

            open_counts[record.task_id] = (
                open_counts.get(record.task_id, 0) + 1
            )

            if status != TASK_STATUS_RUNNING:
                errors.append(
                    f"Execution record {record.id} is open but task "
                    f"{record.task_id} is {status}"
                )

        for task_id, count in open_counts.items():
            if count > 1:
                errors.append(
                    f"Task {task_id} has {count} open execution records"
                )

        return errors

    def _permission_errors(
        self,
        registered_projects: set[str] | None,
    ) -> list[str]:
        """Return the errors found in the grants."""
        if self.permission_registry is None:
            return []

        errors: list[str] = []
        grant_ids: set[str] = set()
        active_pairs: set[tuple[str, str]] = set()

        for grant in self.permission_registry.list_grants(
            include_revoked=True,
        ):
            if grant.id in grant_ids:
                errors.append(f"Duplicate grant ID: {grant.id}")
            else:
                grant_ids.add(grant.id)

            if not grant.is_active:
                continue

            pair = (grant.project, grant.target)

            if pair in active_pairs:
                errors.append(
                    f"Grant {grant.id} duplicates an active grant for "
                    f"target {grant.target} in project {grant.project}"
                )
            else:
                active_pairs.add(pair)

            if (
                registered_projects is not None
                and grant.project not in registered_projects
            ):
                errors.append(
                    f"Grant {grant.id} references unregistered project: "
                    f"{grant.project}"
                )

            if (
                self.known_targets is not None
                and grant.target not in self.known_targets
            ):
                errors.append(
                    f"Grant {grant.id} references unregistered target: "
                    f"{grant.target}"
                )

        return errors

    def _time_errors(
        self,
        goals: list[Goal],
        tasks: list[Task],
    ) -> list[str]:
        """Return the errors found in the stored times.

        Goals and tasks are always checked. Execution records and grants
        are checked only when their registries are given. A time that
        may be empty, such as the end of an open attempt, is not an error
        when it is empty.
        """
        errors: list[str] = []

        for goal in goals:
            errors.extend(
                _unreadable_times(
                    "Goal",
                    goal.id,
                    {
                        "created_at": goal.created_at,
                        "updated_at": goal.updated_at,
                    },
                )
            )

        for task in tasks:
            errors.extend(
                _unreadable_times(
                    "Task",
                    task.id,
                    {
                        "created_at": task.created_at,
                        "updated_at": task.updated_at,
                    },
                )
            )

        if self.record_registry is not None:
            for record in self.record_registry.list_records():
                errors.extend(
                    _unreadable_times(
                        "Execution record",
                        record.id,
                        {
                            "started_at": record.started_at,
                            "ended_at": record.ended_at,
                        },
                        optional=("started_at", "ended_at"),
                    )
                )

        if self.permission_registry is not None:
            for grant in self.permission_registry.list_grants(
                include_revoked=True,
            ):
                errors.extend(
                    _unreadable_times(
                        "Grant",
                        grant.id,
                        {
                            "granted_at": grant.granted_at,
                            "revoked_at": grant.revoked_at,
                        },
                        optional=("revoked_at",),
                    )
                )

        return errors

    def validate(self) -> ValidationResult:
        """Validate the complete persisted goal/task graph."""
        goals = self.goal_registry.list_goals()
        tasks = self.task_registry.list_tasks()
        registered_projects = self._registered_project_names()

        errors: list[str] = []

        goal_ids: set[str] = set()

        for goal in goals:
            if goal.id in goal_ids:
                errors.append(f"Duplicate goal ID: {goal.id}")
            else:
                goal_ids.add(goal.id)

            if goal.status not in KNOWN_GOAL_STATUSES:
                errors.append(
                    f"Goal {goal.id} has unknown status: {goal.status}"
                )

            if (
                registered_projects is not None
                and goal.project not in registered_projects
            ):
                errors.append(
                    f"Goal {goal.id} references unregistered project: "
                    f"{goal.project}"
                )

        task_ids: set[str] = set()
        tasks_by_goal: dict[str, list[Task]] = {}

        for task in tasks:
            if task.id in task_ids:
                errors.append(f"Duplicate task ID: {task.id}")
            else:
                task_ids.add(task.id)

            if task.status not in KNOWN_TASK_STATUSES:
                errors.append(
                    f"Task {task.id} has unknown status: {task.status}"
                )

            if task.goal_id not in goal_ids:
                errors.append(
                    f"Task {task.id} references missing goal: "
                    f"{task.goal_id}"
                )
                continue

            tasks_by_goal.setdefault(task.goal_id, []).append(task)

        for goal in goals:
            if goal.status not in KNOWN_GOAL_STATUSES:
                continue

            derived_status = derive_goal_status(
                tasks_by_goal.get(goal.id, [])
            )

            if goal.status != derived_status:
                errors.append(
                    f"Goal {goal.id} status mismatch: "
                    f"persisted={goal.status}, derived={derived_status}"
                )

        errors.extend(self._project_name_errors())
        errors.extend(self._project_directory_errors())
        errors.extend(self._record_errors(tasks))
        errors.extend(self._permission_errors(registered_projects))
        errors.extend(self._time_errors(goals, tasks))

        return ValidationResult(errors=tuple(errors))


def _unreadable_times(
    kind: str,
    identifier: str,
    times: dict[str, object],
    optional: tuple[str, ...] = (),
) -> list[str]:
    """Return an error for each time that cannot be read.

    A time named in optional may be None. Any other value that is not
    readable, including None, is an error.
    """
    errors: list[str] = []

    for name, value in times.items():
        if value is None and name in optional:
            continue

        if read_time(value) is not None:
            continue

        shown = repr(value)

        if len(shown) > 60:
            shown = shown[:57] + "..."

        errors.append(
            f"{kind} {identifier} has a time that cannot be read in "
            f"{name}: {shown}"
        )

    return errors


def validate_task_creation(goal: Goal) -> str | None:
    """Return an error when a goal cannot receive a new task."""
    if goal.status not in KNOWN_GOAL_STATUSES:
        return (
            f"Goal {goal.id} has unknown status: {goal.status}"
        )

    if goal.status == GOAL_STATUS_COMPLETED:
        return f"Cannot create task for completed goal: {goal.id}"

    if goal.status == GOAL_STATUS_FAILED:
        return f"Cannot create task for failed goal: {goal.id}"

    return None
