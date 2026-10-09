"""Validation for persisted goal and task state."""

from __future__ import annotations

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
    are checked only when a record registry is given.
    """

    def __init__(
        self,
        goal_registry: GoalRegistry | None = None,
        task_registry: TaskRegistry | None = None,
        project_registry: ProjectRegistry | None = None,
        record_registry: ExecutionRecordRegistry | None = None,
    ) -> None:
        self.goal_registry = goal_registry or GoalRegistry()
        self.task_registry = task_registry or TaskRegistry()
        self.project_registry = project_registry
        self.record_registry = record_registry

    def _registered_project_names(self) -> set[str] | None:
        """Return registered project names, or None when not checking."""
        if self.project_registry is None:
            return None

        return {
            project.name
            for project in self.project_registry.list_projects()
        }

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

        errors.extend(self._record_errors(tasks))

        return ValidationResult(errors=tuple(errors))


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
