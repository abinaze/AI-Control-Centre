"""Text for showing the execution attempts of a task."""

from __future__ import annotations

from aic_control_centre.execution.records import ExecutionRecord
from aic_control_centre.tasks.model import TASK_STATUS_RUNNING

UNKNOWN_START = "unknown (before records existed)"


def attempt_lines(
    number: int,
    record: ExecutionRecord,
    task_status: str,
) -> list[str]:
    """Return the lines that show one attempt, the first of them blank.

    The blank line separates the attempt from what came before it. An
    attempt that is open and whose task is not running is marked as one
    that was left open. The same lines are used wherever an attempt is
    shown, so that the places that show one cannot drift apart.
    """
    route = record.source

    if record.target:
        route = f"{route} ({record.target})"

    lines = [
        "",
        f"Attempt {number}",
        f"  Route: {route}",
        f"  Started: {record.started_at or UNKNOWN_START}",
    ]

    if record.is_open:
        lines.append("  Ended: still open")

        if task_status != TASK_STATUS_RUNNING:
            lines.append(
                "  Note: the task is not running, "
                "so this attempt was left open"
            )
    else:
        lines.append(f"  Ended: {record.ended_at}")
        lines.append(f"  Outcome: {record.ended_as}")

    if record.reason:
        lines.append(f"  Reason: {record.reason}")

    return lines
