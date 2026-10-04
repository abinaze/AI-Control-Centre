"""Command-line interface for AI-Control-Centre."""

from __future__ import annotations

import argparse

from aic_control_centre.doctor import run_doctor
from aic_control_centre.goals.commands import (
    create_goal,
    list_goals,
    show_goal_status,
)
from aic_control_centre.projects.commands import add_project, list_projects
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.storage import StateFileError
from aic_control_centre.tasks.commands import (
    complete_task,
    create_task,
    fail_task,
    list_tasks,
    mark_task_ready,
    show_task_readiness,
    show_task_status,
    start_task,
)
from aic_control_centre.validation.goal_tasks import GoalTaskValidator


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="aic",
        description="Local-first autonomous AI development and control platform.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
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

    task_fail_parser = task_subparsers.add_parser(
        "fail",
        help="Mark a running task as failed.",
    )
    task_fail_parser.add_argument(
        "task_id",
        help="Task ID.",
    )

    return parser


def main() -> int:
    """Run the AI-Control-Centre command-line interface."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        return _run(parser, args)
    except StateFileError as exc:
        print(f"Error: {exc}")
        return 1


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Run the command selected by the parsed arguments."""
    if args.command == "doctor":
        return run_doctor()

    if args.command == "validate":
        validator = GoalTaskValidator(project_registry=ProjectRegistry())
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
            return complete_task(args.task_id)

        if args.task_command == "fail":
            return fail_task(args.task_id)

        parser.parse_args(["task", "--help"])
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
