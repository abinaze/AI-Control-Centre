"""Environment diagnostics for AI-Control-Centre."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    """Result of a single environment check."""

    name: str
    passed: bool
    detail: str


def check_python() -> CheckResult:
    """Check that the running Python version is supported."""
    major, minor = sys.version_info[:2]
    passed = (major, minor) >= (3, 11) and (major, minor) < (3, 15)

    return CheckResult(
        name="Python version",
        passed=passed,
        detail=f"Python {major}.{minor}",
    )


def check_command(command: str) -> CheckResult:
    """Check whether a command is available on PATH."""
    available = shutil.which(command) is not None

    return CheckResult(
        name=command,
        passed=available,
        detail="available" if available else "not found",
    )


def run_checks() -> list[CheckResult]:
    """Run all currently supported environment checks."""
    return [
        check_python(),
        check_command("git"),
    ]


def print_report(results: list[CheckResult]) -> None:
    """Print diagnostic results."""
    print("AI-Control-Centre Doctor")
    print()

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")

    print()

    if all(result.passed for result in results):
        print("Doctor: all checks passed.")
    else:
        print("Doctor: one or more checks failed.")


def run_doctor() -> int:
    """Run diagnostics and return a process exit code."""
    results = run_checks()
    print_report(results)

    return 0 if all(result.passed for result in results) else 1
