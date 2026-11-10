"""CLI commands for task management."""

from __future__ import annotations

from datetime import datetime, timezone

from aic_control_centre.config import load_config
from aic_control_centre.execution.adapters import build_adapter_registry
from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import (
    EXECUTION_COORDINATION_COMPLETED,
    ExecutionCoordinator,
)
from aic_control_centre.execution.history import attempt_lines
from aic_control_centre.execution.left_open import (
    LeftOpenRefused,
    close_left_open_attempt,
)
from aic_control_centre.execution.records import (
    ENDED_AS_COMPLETED,
    ENDED_AS_FAILED,
    ENDED_AS_REQUEUED,
    EXECUTION_SOURCE_CLI,
    ExecutionRecordRegistry,
)
from aic_control_centre.execution.run_lock import (
    OWNER_ALIVE,
    OWNER_GONE,
    OWNER_UNKNOWN,
    hold_run_lock,
    remove_run_lock_file,
)
from aic_control_centre.execution.start import ExecutionStarter
from aic_control_centre.goals.archive import GoalArchive
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.locking import StateLockError, state_lock
from aic_control_centre.orchestration.goal_tasks import GoalTaskOrchestrator
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.storage import StateFileError
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_READY,
    TASK_STATUS_RUNNING,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.tasks.running import (
    PROBLEM_FUTURE,
    OWNER_TEXT,
    PROBLEM_UNREADABLE,
    describe_running_tasks,
    filter_older_than,
    format_elapsed,
    owner_of_attempt,
    parse_duration,
)
from aic_control_centre.validation.goal_tasks import validate_task_creation


def create_task(goal_id: str, title: str) -> int:
    """Create and persist a new task for an existing goal.

    A goal that has an archive entry gets no task, because its archive was
    not finished, and a task that is not in the entry could not be archived.
    """
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

    registry = TaskRegistry()

    entry = GoalArchive.beside(registry.registry_path).get_entry(goal.id)

    if entry is not None:
        print(
            f"Error: goal {goal.id} is already archived, and the archive "
            "was not finished; finish it with: "
            f"aic goal archive {goal.id} --reason <text>"
        )
        return 1

    creation_error = validate_task_creation(goal)

    if creation_error is not None:
        print(f"Error: {creation_error}")
        return 1

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

    A run whose owner is alive, which means that the aic process that
    runs it holds its run lock, is refused, because requeueing it would
    run the task twice. There is no way around that: the run ends by
    itself, or the process is stopped. When the owner is gone, the lock
    file that it left behind is removed after the requeue, and a note
    says that its child may still be running.
    """
    if not reason.strip():
        print("Error: a reason is required to requeue a task.")
        return 1

    task = _find_task(task_id)
    data_dir = load_config().data_dir
    attempt = None
    owner = OWNER_UNKNOWN

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

        attempt = _record_registry().get_open_attempt(task.id)

        if attempt is not None:
            owner = owner_of_attempt(
                data_dir,
                _record_registry(),
                attempt,
            )

        if owner == OWNER_ALIVE:
            print(
                f"Error: the run of task {task.id} is still alive: the "
                "aic process that runs it holds its lock. Wait for it to "
                "end, or stop that process, and then requeue."
            )
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

        if owner == OWNER_GONE:
            remove_run_lock_file(data_dir, attempt.id)
            print(
                "Note: the aic process that ran it has ended, and its "
                "child may still be running."
            )

    return result


def _print_archive_hint(task_id: str) -> None:
    """Say where an archived task is, when the archive holds it.

    The archive is only asked after the task was not found among the active
    tasks. An archive that cannot be read gives no hint, and the error that
    was already printed stands.
    """
    try:
        entry = GoalArchive.beside(
            TaskRegistry().registry_path,
        ).find_task_entry(task_id)
    except StateFileError:
        return

    if entry is None:
        return

    print(f"The task is in the archive, in goal {entry.goal.id}.")
    print(f"Show it with: aic goal archived {entry.goal.id}")


def show_task_history(task_id: str) -> int:
    """Show the recorded execution attempts for a task, oldest first."""
    task = TaskRegistry().get_task(task_id)

    if task is None:
        print(f"Error: task not found: {task_id}")
        _print_archive_hint(task_id)
        return 1

    attempts = _record_registry().list_attempts(task.id)

    print(f"Task: {task.id}")
    print(f"Status: {task.status}")

    if not attempts:
        print("No attempts recorded.")
        return 0

    print(f"Attempts: {len(attempts)}")

    for number, record in enumerate(attempts, start=1):
        for line in attempt_lines(number, record, task.status):
            print(line)

    return 0


def run_task(task_id: str, target: str) -> int:
    """Run a ready task through the execution adapter for a target.

    The task is started, the adapter runs, and its outcome is recorded.
    A target that needs a grant runs only for a project that has an
    active grant for it in the permission registry. A target that acts
    on a project's files runs only if the project is registered and its
    directory exists.
    The state lock is held only while state is read or written, never
    while the adapter runs, so other commands, including requeue, still
    work during a long run.
    A run lock, which is a different lock, is held for the whole run, so
    that another process can tell that this one is alive. If it cannot
    be taken, the run goes on and a note says so.

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

    def run_guard(attempt_id):
        return hold_run_lock(data_dir, attempt_id)

    permissions = PermissionRegistry.beside(TaskRegistry().registry_path)
    coordinator = ExecutionCoordinator(
        adapter_registry=build_adapter_registry(),
        starter=ExecutionStarter(
            admission=ExecutionAdmission(
                grants=permissions,
                projects=ProjectRegistry(),
            ),
        ),
        state_guard=guard,
        run_guard=run_guard,
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
    except KeyboardInterrupt:
        print("Interrupted.")
        print(
            "Check the task with aic task status. If it is running, "
            "use aic task complete, fail, or requeue."
        )
        return 130

    print(f"Task: {result.task_id}")
    print(f"Target: {target.strip()}")
    print(f"Result: {result.status}")
    print(f"Reason: {result.reason}")

    if result.note is not None:
        print(f"Note: {result.note}")

    if result.status == EXECUTION_COORDINATION_COMPLETED:
        return 0

    return 1


def _now() -> datetime:
    """Return the current time, with its time zone."""
    return datetime.now(timezone.utc)


def close_task_attempt(task_id: str, reason: str) -> int:
    """Close the attempt that a finished task left open.

    This is the way out of the state that a failed write leaves when a
    task is completed or failed: the task is final and its attempt is
    still open, and nothing starts a final task again. The attempt gets
    the outcome that the task already has, and the reason that a person
    gave, kept with a beginning that says that it was closed afterwards.

    Everything else is refused, and a refusal writes nothing: a task that
    is not completed or failed, a task with no open attempt, a task with
    more than one, and a run whose owner is alive. The goal is not
    touched. aic goal status reconciles a goal.
    """
    try:
        result = close_left_open_attempt(
            TaskRegistry(),
            _record_registry(),
            task_id,
            reason,
            load_config().data_dir,
        )
    except LeftOpenRefused as exc:
        print(f"Error: {exc}")
        return 1

    record = result.record

    print(f"Attempt closed: {record.id}")
    print(f"Task: {record.task_id}")
    print(f"Outcome: {record.ended_as}")
    print(f"Reason: {record.reason}")

    return 0


def show_running_tasks(older_than: str | None = None) -> int:
    """List the running tasks and how long each has been running.

    The time is advisory. A task that is listed may still be running,
    and nothing is written or changed. The tasks are listed with the
    longest running first. The owner line says whether the aic process
    that runs the task is alive, gone or unknown, from its run lock.
    """
    threshold = None

    if older_than is not None:
        try:
            threshold = parse_duration(older_than)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1

    rows = describe_running_tasks(
        TaskRegistry(),
        _record_registry(),
        _now(),
        load_config().data_dir,
    )

    if threshold is not None:
        rows = filter_older_than(rows, threshold)

    if not rows:
        if older_than is None:
            print("No running tasks.")
        else:
            print(f"No running tasks older than {older_than.strip()}.")

        return 0

    print(f"Running tasks: {len(rows)}")
    print()

    for row in rows:
        since = row.since

        if row.estimated:
            since = f"{since} (estimated from the last update)"

        if row.problem == PROBLEM_UNREADABLE:
            running_for = "unknown (the start time cannot be read)"
        elif row.problem == PROBLEM_FUTURE:
            running_for = "0s (the start time is in the future)"
        else:
            running_for = format_elapsed(row.elapsed)

        print(f"- {row.task_id}")
        print(f"  Title: {row.title}")
        print(f"  Goal: {row.goal_id}")
        print(f"  Route: {row.route}")
        print(f"  Since: {since}")
        print(f"  Running for: {running_for}")
        print(f"  Owner: {OWNER_TEXT[row.owner]}")
        print()

    print(
        "A task listed here may still be running. "
        "Requeueing a live run runs the task twice."
    )
    print("aic task requeue refuses a run whose owner is alive.")
    print(
        "To put a task back in the queue: "
        'aic task requeue <task-id> --reason "<text>"'
    )

    return 0


def list_targets() -> int:
    """List the execution targets that aic task run can use."""
    registry = build_adapter_registry()
    targets = registry.list_targets()

    if not targets:
        print("No execution targets registered.")
        return 0

    print(f"Execution targets: {len(targets)}")

    for target in targets:
        adapter = registry.resolve(target)
        description = getattr(adapter, "description", "")

        if getattr(adapter, "requires_grant", True):
            grant_note = "needs a grant"
        else:
            grant_note = "needs no grant"

        if description:
            print(f"{target}: {description} ({grant_note})")
        else:
            print(f"{target} ({grant_note})")

    return 0
