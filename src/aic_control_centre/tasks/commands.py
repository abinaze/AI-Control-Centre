"""CLI commands for task management."""

from __future__ import annotations

from aic_control_centre.config import load_config
from aic_control_centre.execution.adapters import build_adapter_registry
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import (
    EXECUTION_COORDINATION_COMPLETED,
    ExecutionCoordinator,
)
from aic_control_centre.execution.records import (
    ENDED_AS_COMPLETED,
    ENDED_AS_FAILED,
    ENDED_AS_REQUEUED,
    EXECUTION_SOURCE_CLI,
    ExecutionRecordRegistry,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.locking import StateLockError, state_lock
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


def _finish_task(
    task_id: str,
    new_status: str,
    ended_as: str,
    reason: str | None = None,
) -> int:
    """Move a running task to a final status and close its attempt.

    The task moves first and the attempt record is closed after it. A
    crash in between leaves an open record for a task that is no longer
    running, which is detectable.

    A reason is optional. If one is given it is stored in the attempt
    record and printed. A blank reason is refused before anything changes.
    """
    if reason is not None and not reason.strip():
        print("Error: a reason cannot be blank.")
        return 1

    result = transition_task_status(task_id=task_id, new_status=new_status)

    if result == 0:
        _record_registry().close_attempt(
            task_id=task_id.strip(),
            ended_as=ended_as,
            reason=reason or "",
            source=EXECUTION_SOURCE_CLI,
        )

        if reason is not None:
            print(f"Reason: {reason.strip()}")

    return result


def complete_task(task_id: str, reason: str | None = None) -> int:
    """Move a running task to the completed state and close its attempt."""
    return _finish_task(
        task_id,
        TASK_STATUS_COMPLETED,
        ENDED_AS_COMPLETED,
        reason,
    )


def fail_task(task_id: str, reason: str | None = None) -> int:
    """Move a running task to the failed state and close its attempt."""
    return _finish_task(
        task_id,
        TASK_STATUS_FAILED,
        ENDED_AS_FAILED,
        reason,
    )


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


def show_task_history(task_id: str) -> int:
    """Show the recorded execution attempts for a task, oldest first."""
    task = TaskRegistry().get_task(task_id)

    if task is None:
        print(f"Error: task not found: {task_id}")
        return 1

    attempts = _record_registry().list_attempts(task.id)

    print(f"Task: {task.id}")
    print(f"Status: {task.status}")

    if not attempts:
        print("No attempts recorded.")
        return 0

    print(f"Attempts: {len(attempts)}")

    for number, record in enumerate(attempts, start=1):
        route = record.source

        if record.target:
            route = f"{route} ({record.target})"

        print()
        print(f"Attempt {number}")
        print(f"  Route: {route}")
        print(
            "  Started: "
            f"{record.started_at or 'unknown (before records existed)'}"
        )

        if record.is_open:
            print("  Ended: still open")

            if task.status != TASK_STATUS_RUNNING:
                print(
                    "  Note: the task is not running, "
                    "so this attempt was left open"
                )
        else:
            print(f"  Ended: {record.ended_at}")
            print(f"  Outcome: {record.ended_as}")

        if record.reason:
            print(f"  Reason: {record.reason}")

    return 0


def run_task(task_id: str, target: str) -> int:
    """Run a ready task through the execution adapter for a target.

    The task is started, the adapter runs, and its outcome is recorded.
    The state lock is held only while state is read or written, never
    while the adapter runs, so other commands, including requeue, still
    work during a long run.

    If the lock cannot be taken to record the outcome, the adapter has
    already run. The task is then left running with its attempt open,
    which is the same shape a crash leaves and which requeue recovers.
    """
    if not task_id.strip():
        print("Error: task ID cannot be empty.")
        return 1

    if not target.strip():
        print("Error: execution target cannot be empty.")
        return 1

    data_dir = load_config().data_dir
    guard_calls = []

    def guard():
        guard_calls.append(1)
        return state_lock(data_dir)

    coordinator = ExecutionCoordinator(
        adapter_registry=build_adapter_registry(),
        state_guard=guard,
    )

    try:
        result = coordinator.coordinate(
            ExecutionRequest(task_id=task_id.strip(), target=target.strip()),
        )
    except StateLockError as exc:
        if len(guard_calls) < 2:
            raise

        print(f"Error: {exc}")
        print("The adapter has run, but its outcome was not recorded.")
        print(
            "The task is still running. "
            "Use aic task complete, fail, or requeue."
        )
        return 1

    print(f"Task: {result.task_id}")
    print(f"Target: {target.strip()}")
    print(f"Result: {result.status}")
    print(f"Reason: {result.reason}")

    if result.status == EXECUTION_COORDINATION_COMPLETED:
        return 0

    return 1


def list_targets() -> int:
    """List the execution targets that aic task run can use."""
    registry = build_adapter_registry()
    targets = registry.list_targets()

    if not targets:
        print("No execution targets registered.")
        return 0

    print(f"Execution targets: {len(targets)}")

    for target in targets:
        description = getattr(registry.resolve(target), "description", "")

        if description:
            print(f"{target}: {description}")
        else:
            print(target)

    return 0
