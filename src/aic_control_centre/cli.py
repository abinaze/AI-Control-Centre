"""Command-line interface for AI-Control-Centre."""

from __future__ import annotations

import argparse

from aic_control_centre.doctor import run_doctor


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

    return parser


def main() -> int:
    """Run the AI-Control-Centre command-line interface."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "doctor":
        return run_doctor()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
