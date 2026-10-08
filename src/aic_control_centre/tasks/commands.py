"""CLI commands for task management."""

from __future__ import annotations

from aic_control_centre.execution.records import (
    ENDED_AS_COMPLETED,
    ENDED_AS_FAILED,
    ENDED_AS_REQUEUED,
    EXECUTION_SOURCE_CLI,
    ExecutionRecordRegistry,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.orchestration.goal_tasks import GoalTaskOrchestrator
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_READY,
    TASK_STATUS_RUNNING,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.validation.goal_tasks import validate_task_creation


def create_task(goal_id: str, title: str) -> int:
    """Create and persist a new task for an existing goal."""
    if not goal_id.strip():
        print("Error: goal ID cannot be empty.")
        return 1

    if not title.strip():
        print("Error: task title cannot be empty.")
        return 1

    goal = GoalRegistry().get_goal(goal_id.strip())

    if goal is None:
        print(f"Error: goal not found: {goal_id}")
        return 1

    creation_error = validate_task_creation(goal)

    if creation_error is not None:
        print(f"Error: {creation_error}")
        return 1

    registry = TaskRegistry()

    task = Task.create(
        goal_id=goal.id,
        title=title.strip(),
    )

    registry.add_task(task)

    GoalTaskOrchestrator(
        goal_registry=GoalRegistry(),
        task_registry=registry,
    ).reconcile_goal(goal.id)

    print("Task created.")
    print(f"ID: {task.id}")
    print(f"Goal: {task.goal_id}")
    print(f"Status: {task.status}")
    print(f"Title: {task.title}")

    return 0


def list_tasks() -> int:
    """List all registered tasks."""
    registry = TaskRegistry()
    tasks = registry.list_tasks()

    if not tasks:
        print("No tasks registered.")
        return 0

    print("Registered tasks:")
    print()

    for task in tasks:
        print(f"- {task.id}")
        print(f"  Goal: {task.goal_id}")
        print(f"  Status: {task.status}")
        print(f"  Title: {task.title}")
        print(f"  Created: {task.created_at}")
        print()

    return 0


def show_task_status(task_id: str) -> int:
    """Show the status and details of a task."""
    registry = TaskRegistry()
    task = registry.get_task(task_id)

    if task is None:
        print(f"Error: task not found: {task_id}")
        return 1

    print(f"Task: {task.id}")
    print(f"Goal: {task.goal_id}")
    print(f"Status: {task.status}")
    print(f"Title: {task.title}")
    print(f"Description: {task.description}")
    print(f"Created: {task.created_at}")
    print(f"Updated: {task.updated_at}")

    return 0


def show_task_readiness(task_id: str) -> int:
    """Show whether a task is ready for execution."""
    if not task_id.strip():
        print("Error: task ID cannot be empty.")
        return 1

    result = TaskReadinessEvaluator().evaluate(task_id.strip())

    print(f"Task: {result.task_id}")
    print(f"Ready: {'yes' if result.ready else 'no'}")
    print(f"Reason: {result.reason}")

    return 0 if result.ready else 1


def transition_task_status(task_id: str, new_status: str) -> int:
    """Transition a task to a requested lifecycle status."""
    if not task_id.strip():
        print("Error: task ID cannot be empty.")
        return 1

    registry = TaskRegistry()

    try:
        task = registry.update_task_status(
            task_id=task_id.strip(),
            new_status=new_status,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    GoalTaskOrchestrator(
        goal_registry=GoalRegistry(),
        task_registry=registry,
    ).reconcile_goal(task.goal_id)

    print("Task status updated.")
    print(f"ID: {task.id}")
    print(f"Status: {task.status}")

    return 0


def _find_task(task_id: str) -> Task | None:
    """Return the persisted task for an ID, or None if there is none."""
    cleaned = task_id.strip()

    if not cleaned:
        return None

    return TaskRegistry().get_task(cleaned)


def _readiness_evaluator() -> TaskReadinessEvaluator:
    """Build a readiness evaluator over the command registries."""
    return TaskReadinessEvaluator(
        goal_registry=GoalRegistry(),
        task_registry=TaskRegistry(),
    )


def _record_registry() -> ExecutionRecordRegistry:
    """Build the execution record registry beside the task file."""
    return ExecutionRecordRegistry.beside(TaskRegistry().registry_path)


def mark_task_ready(task_id: str) -> int:
    """Move a pending task to the ready state.

    The parent goal must still be open. Task readiness cannot be checked
    here, because the task is not ready until this transition happens.

    A running task is refused. Sending it back to ready is a recovery
    action that needs a reason, so it is done only by `aic task requeue`.
    """
    task = _find_task(task_id)

    if task is not None:
        if task.status == TASK_STATUS_RUNNING:
            print("Error: task is running and cannot be marked ready.")
            print(
                "To retry it, use: "
                f'aic task requeue {task.id} --reason "<text>"'
            )
            return 1

        blocker = _readiness_evaluator().parent_goal_blocker(task.goal_id)

        if blocker is not None:
            print(f"Error: task cannot be marked ready: {blocker}")
            return 1

    return transition_task_status(
        task_id=task_id,
        new_status=TASK_STATUS_READY,
    )


def start_task(task_id: str) -> int:
    """Move a ready task to the running state.

    The task must pass the readiness boundary first. Empty and unknown
    task IDs are left to the lifecycle transition to report.

    An attempt record is opened before the task moves to running. A
    crash in between leaves an open record and a ready task, which is
    detectable. The other order could leave a running task with no
    start time.
    """
    task = _find_task(task_id)

    if task is not None:
        readiness = _readiness_evaluator().evaluate(task.id)

        if not readiness.ready:
            print(
                "Error: task is not ready for execution: "
                f"{readiness.reason}"
            )
            return 1

        _record_registry().open_attempt(
            task_id=task.id,
            source=EXECUTION_SOURCE_CLI,
        )

    return transition_task_status(
        task_id=task_id,
        new_status=TASK_STATUS_RUNNING,
    )


def _finish_task(task_id: str, new_status: str, ended_as: str) -> int:
    """Move a running task to a final status and close its attempt.

    The task moves first and the attempt record is closed after it. A
    crash in between leaves an open record for a task that is no longer
    running, which is detectable.
    """
    result = transition_task_status(task_id=task_id, new_status=new_status)

    if result == 0:
        _record_registry().close_attempt(
            task_id=task_id.strip(),
            ended_as=ended_as,
            source=EXECUTION_SOURCE_CLI,
        )

    return result


def complete_task(task_id: str) -> int:
    """Move a running task to the completed state and close its attempt."""
    return _finish_task(task_id, TASK_STATUS_COMPLETED, ENDED_AS_COMPLETED)


def fail_task(task_id: str) -> int:
    """Move a running task to the failed state and close its attempt."""
    return _finish_task(task_id, TASK_STATUS_FAILED, ENDED_AS_FAILED)


def requeue_task(task_id: str, reason: str) -> int:
    """Return a running task to the ready state so it can be retried.

    This is the recovery path for a task whose process is gone and
    never recorded an outcome. A person decides that the run is dead,
    so a reason is required. The reason is printed and kept in the
    attempt record, which is closed after the task has moved to ready.

    The task must be running and its parent goal must be open. The
    task is not started: starting still goes through readiness. Empty
    and unknown task IDs are left to the lifecycle transition to report.
    """
    if not reason.strip():
        print("Error: a reason is required to requeue a task.")
        return 1

    task = _find_task(task_id)

    if task is not None:
        if task.status != TASK_STATUS_RUNNING:
            print(
                "Error: only a running task can be requeued "
                f"(task status is {task.status})."
            )
            return 1

        blocker = _readiness_evaluator().parent_goal_blocker(task.goal_id)

        if blocker is not None:
            print(f"Error: task cannot be requeued: {blocker}")
            return 1

    result = transition_task_status(
        task_id=task_id,
        new_status=TASK_STATUS_READY,
    )

    if task is not None and result == 0:
        _record_registry().close_attempt(
            task_id=task.id,
            ended_as=ENDED_AS_REQUEUED,
            reason=reason,
            source=EXECUTION_SOURCE_CLI,
        )

        print(f"Previous status: running (last updated {task.updated_at})")
        print(f"Reason: {reason.strip()}")

    return result
