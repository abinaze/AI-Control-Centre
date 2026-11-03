"""Text for showing an archived goal with its tasks and their attempts."""

from __future__ import annotations

from aic_control_centre.execution.history import attempt_lines
from aic_control_centre.goals.archive import ArchiveEntry


def archived_goal_lines(entry: ArchiveEntry) -> list[str]:
    """Return the lines that show an archived goal and what it held.

    The goal comes first, as the listing of the archive shows it. Then each
    task follows in the order in which it was archived, with its attempts in
    the lines that aic task history uses, because both are made by the same
    function. Nothing here reads or changes any file.
    """
    goal = entry.goal
    lines = [
        f"Archived goal: {goal.id}",
        f"Project: {goal.project}",
        f"Directory: {entry.project_path or 'not recorded'}",
        f"Status: {goal.status}",
        f"Description: {goal.description}",
        f"Archived: {entry.archived_at}",
        f"Reason: {entry.reason}",
        f"Tasks: {len(entry.tasks)}",
    ]

    for task in entry.tasks:
        attempts = [
            record for record in entry.records if record.task_id == task.id
        ]

        lines.extend(
            [
                "",
                f"Task: {task.id}",
                f"Status: {task.status}",
                f"Title: {task.title}",
            ]
        )

        if task.description:
            lines.append(f"Description: {task.description}")

        if not attempts:
            lines.append("No attempts recorded.")
            continue

        lines.append(f"Attempts: {len(attempts)}")

        for number, record in enumerate(attempts, start=1):
            lines.extend(attempt_lines(number, record, task.status))

    return lines
