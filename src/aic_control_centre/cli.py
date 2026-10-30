"""Command-line interface for AI-Control-Centre."""

from __future__ import annotations

import argparse

from aic_control_centre import __version__
from aic_control_centre.config import load_config
from aic_control_centre.doctor import run_doctor
from aic_control_centre.execution.adapters import build_adapter_registry
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.goals.commands import (
    create_goal,
    list_goals,
    show_goal_status,
)
from aic_control_centre.locking import StateLockError, state_lock
from aic_control_centre.permissions.commands import (
    grant_permission,
    list_permissions,
    revoke_permission,
)
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.commands import (
    add_project,
    list_projects,
    remove_project,
)
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.storage import StateFileError
from aic_control_centre.tasks.commands import (
    complete_task,
    create_task,
    fail_task,
    list_targets,
    list_tasks,
    mark_task_ready,
    requeue_task,
    run_task,
    show_running_tasks,
    show_task_history,
    show_task_readiness,
    show_task_status,
    start_task,
)
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.validation.goal_tasks import GoalTaskValidator

# Commands that never write state, and so do not take the state lock.
# Every other command locks for its whole run, including any command added
# later, until someone decides that it only reads and lists it here.
READ_ONLY_COMMANDS = frozenset(
    {
        "doctor",
        "project list",
        "goal list",
        "task list",
        "task status",
        "task readiness",
        "task history",
        "task targets",
        "task running",
        "permission list",
    }
)

# Commands that take the state lock themselves, around each state
# operation, because they run something slow in between. main does not
# lock them, and a command listed here must never hold the lock while that
# work runs.
SELF_LOCKING_COMMANDS = frozenset({"task run"})


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="aic",
        description="Local-first deterministic control platform for AI work.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "doctor",
        help="Check the local AI-Control-Centre environment.",
    )

    subparsers.add_parser(
        "validate",
        help="Validate persisted goal and task state.",
    )

    project_parser = subparsers.add_parser(
        "project",
        help="Manage registered local projects.",
    )

    project_subparsers = project_parser.add_subparsers(
        dest="project_command",
    )

    project_add_parser = project_subparsers.add_parser(
        "add",
        help="Register a local project.",
    )
    project_add_parser.add_argument(
        "path",
        help="Path to the local project.",
    )

    project_subparsers.add_parser(
        "list",
        help="List registered projects.",
    )

    project_remove_parser = project_subparsers.add_parser(
        "remove",
        help=(
            "Remove a project from the registry. "
            "Its directory is not touched."
        ),
    )
    project_remove_parser.add_argument(
        "name",
        help="Name of the registered project.",
    )
    project_remove_parser.add_argument(
        "--path",
        default=None,
        help="Directory of the project, when more than one has the name.",
    )

    goal_parser = subparsers.add_parser(
        "goal",
        help="Create and manage high-level goals.",
    )

    goal_subparsers = goal_parser.add_subparsers(
        dest="goal_command",
    )

    goal_create_parser = goal_subparsers.add_parser(
        "create",
        help="Create a new goal.",
    )
    goal_create_parser.add_argument(
        "description",
        help="Goal description.",
    )
    goal_create_parser.add_argument(
        "--project",
        required=True,
        help="Registered project name.",
    )

    goal_subparsers.add_parser(
        "list",
        help="List registered goals.",
    )

    goal_status_parser = goal_subparsers.add_parser(
        "status",
        help="Show a goal and its current status.",
    )
    goal_status_parser.add_argument(
        "goal_id",
        help="Goal ID.",
    )

    task_parser = subparsers.add_parser(
        "task",
        help="Create and manage tasks.",
    )

    task_subparsers = task_parser.add_subparsers(
        dest="task_command",
    )

    task_create_parser = task_subparsers.add_parser(
        "create",
        help="Create a new task for a goal.",
    )
    task_create_parser.add_argument(
        "--goal",
        required=True,
        help="Goal ID.",
    )
    task_create_parser.add_argument(
        "title",
        help="Task title.",
    )

    task_subparsers.add_parser(
        "list",
        help="List registered tasks.",
    )

    task_status_parser = task_subparsers.add_parser(
        "status",
        help="Show a task and its current status.",
    )
    task_status_parser.add_argument(
        "task_id",
        help="Task ID.",
    )

    task_readiness_parser = task_subparsers.add_parser(
        "readiness",
        help="Check whether a task is ready for execution.",
    )
    task_readiness_parser.add_argument(
        "task_id",
        help="Task ID.",
    )

    task_ready_parser = task_subparsers.add_parser(
        "ready",
        help="Move a pending task to ready.",
    )
    task_ready_parser.add_argument(
        "task_id",
        help="Task ID.",
    )

    task_start_parser = task_subparsers.add_parser(
        "start",
        help="Move a ready task to running.",
    )
    task_start_parser.add_argument(
        "task_id",
        help="Task ID.",
    )

    task_complete_parser = task_subparsers.add_parser(
        "complete",
        help="Mark a running task as completed.",
    )
    task_complete_parser.add_argument(
        "task_id",
        help="Task ID.",
    )
    task_complete_parser.add_argument(
        "--reason",
        help="Why the task is being completed. Kept in its attempt record.",
    )

    task_fail_parser = task_subparsers.add_parser(
        "fail",
        help="Mark a running task as failed.",
    )
    task_fail_parser.add_argument(
        "task_id",
        help="Task ID.",
    )
    task_fail_parser.add_argument(
        "--reason",
        help="Why the task failed. Kept in its attempt record.",
    )

    task_requeue_parser = task_subparsers.add_parser(
        "requeue",
        help="Return a running task to ready so it can be retried.",
    )
    task_requeue_parser.add_argument(
        "task_id",
        help="Task ID.",
    )
    task_requeue_parser.add_argument(
        "--reason",
        required=True,
        help="Why the task is being requeued.",
    )

    task_history_parser = task_subparsers.add_parser(
        "history",
        help="Show the recorded execution attempts for a task.",
    )
    task_history_parser.add_argument(
        "task_id",
        help="Task ID.",
    )

    task_run_parser = task_subparsers.add_parser(
        "run",
        help="Run a ready task through an execution target.",
    )
    task_run_parser.add_argument(
        "task_id",
        help="Task ID.",
    )
    task_run_parser.add_argument(
        "--target",
        required=True,
        help="Execution target to run the task on. See aic task targets.",
    )

    task_subparsers.add_parser(
        "targets",
        help="List the execution targets that aic task run can use.",
    )

    task_running_parser = task_subparsers.add_parser(
        "running",
        help="List the running tasks and how long each has been running.",
    )
    task_running_parser.add_argument(
        "--older-than",
        dest="older_than",
        metavar="DURATION",
        help=(
            "Only list tasks that have been running for at least this "
            "long, for example 30m, 2h or 1d."
        ),
    )

    permission_parser = subparsers.add_parser(
        "permission",
        help="Manage which projects may use which execution targets.",
    )

    permission_subparsers = permission_parser.add_subparsers(
        dest="permission_command",
    )

    permission_grant_parser = permission_subparsers.add_parser(
        "grant",
        help="Let a project use an execution target.",
    )
    permission_grant_parser.add_argument(
        "project",
        help="Registered project name.",
    )
    permission_grant_parser.add_argument(
        "--target",
        required=True,
        help="Execution target. See aic task targets.",
    )
    permission_grant_parser.add_argument(
        "--reason",
        required=True,
        help="Why the project may use the target.",
    )

    permission_revoke_parser = permission_subparsers.add_parser(
        "revoke",
        help="Withdraw a project's permission to use an execution target.",
    )
    permission_revoke_parser.add_argument(
        "project",
        help="Project name.",
    )
    permission_revoke_parser.add_argument(
        "--target",
        required=True,
        help="Execution target.",
    )

    permission_list_parser = permission_subparsers.add_parser(
        "list",
        help="List the permissions that are granted.",
    )
    permission_list_parser.add_argument(
        "--all",
        action="store_true",
        dest="include_revoked",
        help="Include permissions that were revoked.",
    )

    return parser


def _command_key(args: argparse.Namespace) -> str | None:
    """Return the command name as READ_ONLY_COMMANDS spells it.

    A command with subcommands is named "group subcommand", such as
    "task start". None means no command was chosen, or a group was
    given without a subcommand; both only print help.
    """
    if args.command is None:
        return None

    attribute = f"{args.command}_command"

    if not hasattr(args, attribute):
        return args.command

    subcommand = getattr(args, attribute)

    if subcommand is None:
        return None

    return f"{args.command} {subcommand}"


def _needs_state_lock(args: argparse.Namespace) -> bool:
    """Return whether main must hold the state lock for the whole command.

    Commands lock unless they are listed in READ_ONLY_COMMANDS or
    SELF_LOCKING_COMMANDS, so a command that nobody has classified is
    protected. A command that only prints help touches no state and takes
    no lock.
    """
    key = _command_key(args)

    if key is None:
        return False

    return key not in READ_ONLY_COMMANDS | SELF_LOCKING_COMMANDS


def main() -> int:
    """Run the AI-Control-Centre command-line interface."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        if _needs_state_lock(args):
            with state_lock(load_config().data_dir):
                return _run(parser, args)

        return _run(parser, args)
    except (StateFileError, StateLockError) as exc:
        print(f"Error: {exc}")
        return 1


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Run the command selected by the parsed arguments."""
    if args.command == "doctor":
        return run_doctor()

    if args.command == "validate":
        validator = GoalTaskValidator(
            project_registry=ProjectRegistry(),
            record_registry=ExecutionRecordRegistry.beside(
                TaskRegistry().registry_path,
            ),
            permission_registry=PermissionRegistry.beside(
                TaskRegistry().registry_path,
            ),
            known_targets=build_adapter_registry().list_targets(),
        )
        result = validator.validate()

        if result.valid:
            print("Validation passed.")
            return 0

        print("Validation failed.")

        for error in result.errors:
            print(f"- {error}")

        return 1

    if args.command == "project":
        if args.project_command == "add":
            return add_project(args.path)

        if args.project_command == "list":
            return list_projects()

        if args.project_command == "remove":
            return remove_project(args.name, args.path)

        parser.parse_args(["project", "--help"])
        return 0

    if args.command == "goal":
        if args.goal_command == "create":
            return create_goal(
                description=args.description,
                project=args.project,
            )

        if args.goal_command == "list":
            return list_goals()

        if args.goal_command == "status":
            return show_goal_status(args.goal_id)

        parser.parse_args(["goal", "--help"])
        return 0

    if args.command == "permission":
        if args.permission_command == "grant":
            return grant_permission(
                project=args.project,
                target=args.target,
                reason=args.reason,
            )

        if args.permission_command == "revoke":
            return revoke_permission(
                project=args.project,
                target=args.target,
            )

        if args.permission_command == "list":
            return list_permissions(include_revoked=args.include_revoked)

        parser.parse_args(["permission", "--help"])
        return 0

    if args.command == "task":
        if args.task_command == "create":
            return create_task(
                goal_id=args.goal,
                title=args.title,
            )

        if args.task_command == "list":
            return list_tasks()

        if args.task_command == "status":
            return show_task_status(args.task_id)

        if args.task_command == "readiness":
            return show_task_readiness(args.task_id)

        if args.task_command == "ready":
            return mark_task_ready(args.task_id)

        if args.task_command == "start":
            return start_task(args.task_id)

        if args.task_command == "complete":
            return complete_task(
                task_id=args.task_id,
                reason=args.reason,
            )

        if args.task_command == "fail":
            return fail_task(
                task_id=args.task_id,
                reason=args.reason,
            )

        if args.task_command == "requeue":
            return requeue_task(
                task_id=args.task_id,
                reason=args.reason,
            )

        if args.task_command == "history":
            return show_task_history(args.task_id)

        if args.task_command == "run":
            return run_task(task_id=args.task_id, target=args.target)

        if args.task_command == "targets":
            return list_targets()

        if args.task_command == "running":
            return show_running_tasks(older_than=args.older_than)

        parser.parse_args(["task", "--help"])
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
