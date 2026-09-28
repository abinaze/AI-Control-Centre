"""Command-line interface for AI-Control-Centre."""

from __future__ import annotations

import argparse

from aic_control_centre.doctor import run_doctor
from aic_control_centre.projects.commands import add_project, list_projects


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

    return parser


def main() -> int:
    """Run the AI-Control-Centre command-line interface."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "doctor":
        return run_doctor()

    if args.command == "project":
        if args.project_command == "add":
            return add_project(args.path)

        if args.project_command == "list":
            return list_projects()

        parser.parse_args(["project", "--help"])
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
