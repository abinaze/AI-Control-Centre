"""Tests for the text of an archived goal."""

from dataclasses import replace

from aic_control_centre.execution.history import attempt_lines
from aic_control_centre.execution.records import ExecutionRecord
from aic_control_centre.goals.archive import ArchiveEntry
from aic_control_centre.goals.archive_view import archived_goal_lines
from aic_control_centre.goals.model import Goal
from aic_control_centre.tasks.model import Task

START = "2026-10-30T00:00:00+00:00"
END = "2026-10-30T00:00:01+00:00"


def _goal():
    goal = Goal.create("Ship it", "app")

    return replace(goal, status="completed")


def _task(goal, title, status="completed", description=""):
    task = Task.create(goal.id, title)

    return replace(task, status=status, description=description)


def _record(task, number, **fields):
    values = {
        "id": f"record-{number}",
        "task_id": task.id,
        "source": "coordinator",
        "target": "noop",
        "started_at": START,
        "ended_at": END,
        "ended_as": "completed",
        "reason": "",
    }
    values.update(fields)

    return ExecutionRecord(**values)


def _entry(goal, tasks, records, project_path="/work/app"):
    return ArchiveEntry(
        goal=goal,
        tasks=tuple(tasks),
        records=tuple(records),
        archived_at="2026-10-31T00:00:00+00:00",
        reason="all shipped",
        project_path=project_path,
    )


def test_the_goal_is_shown_before_its_tasks() -> None:
    """The header says what the listing says, and how many tasks follow."""
    goal = _goal()

    lines = archived_goal_lines(_entry(goal, [], []))

    assert lines == [
        f"Archived goal: {goal.id}",
        "Project: app",
        "Directory: /work/app",
        "Status: completed",
        "Description: Ship it",
        "Archived: 2026-10-31T00:00:00+00:00",
        "Reason: all shipped",
        "Tasks: 0",
    ]


def test_a_goal_whose_directory_was_not_recorded_says_so() -> None:
    """The line is there, and it says that nothing was recorded."""
    lines = archived_goal_lines(_entry(_goal(), [], [], project_path=None))

    assert "Directory: not recorded" in lines


def test_a_task_with_attempts_is_shown_with_them() -> None:
    """The attempts are the lines that aic task history uses."""
    goal = _goal()
    task = _task(goal, "first")
    record = _record(task, 1, reason="done")

    lines = archived_goal_lines(_entry(goal, [task], [record]))

    assert lines[8:] == [
        "",
        f"Task: {task.id}",
        "Status: completed",
        "Title: first",
        "Attempts: 1",
        "",
        "Attempt 1",
        "  Route: coordinator (noop)",
        f"  Started: {START}",
        f"  Ended: {END}",
        "  Outcome: completed",
        "  Reason: done",
    ]
    assert lines[13:] == attempt_lines(1, record, "completed")


def test_a_task_with_no_attempts_says_so() -> None:
    """There is no Attempts line, as in aic task history."""
    goal = _goal()
    task = _task(goal, "never ran", status="failed")

    lines = archived_goal_lines(_entry(goal, [task], []))

    assert lines[8:] == [
        "",
        f"Task: {task.id}",
        "Status: failed",
        "Title: never ran",
        "No attempts recorded.",
    ]


def test_a_description_is_shown_only_when_there_is_one() -> None:
    """A task without a description has no empty line for it."""
    goal = _goal()
    described = _task(goal, "with", description="Do the thing")
    plain = _task(goal, "without")

    lines = archived_goal_lines(_entry(goal, [described, plain], []))

    assert "Description: Do the thing" in lines
    assert sum(1 for line in lines if line.startswith("Description:")) == 2
    assert lines.count("Title: without") == 1


def test_tasks_and_attempts_keep_the_order_they_were_archived_in() -> None:
    """Each task gets its own records, oldest first, whatever the mix."""
    goal = _goal()
    first = _task(goal, "first")
    second = _task(goal, "second")
    records = [
        _record(second, 1, reason="second one"),
        _record(first, 2, reason="first one"),
        _record(second, 3, reason="second two"),
    ]

    lines = archived_goal_lines(_entry(goal, [first, second], records))
    text = "\n".join(lines)

    assert text.index(f"Task: {first.id}") < text.index(f"Task: {second.id}")
    assert "Attempts: 1" in lines
    assert "Attempts: 2" in lines
    assert text.index("first one") < text.index("second one")
    assert text.index("second one") < text.index("second two")
    assert lines.count("Attempt 1") == 2
    assert lines.count("Attempt 2") == 1


def test_a_task_with_two_attempts_numbers_them_from_one() -> None:
    """The second attempt is numbered 2, as in aic task history."""
    goal = _goal()
    task = _task(goal, "twice")
    records = [_record(task, 1), _record(task, 2, ended_as="failed")]

    lines = archived_goal_lines(_entry(goal, [task], records))

    assert "Attempts: 2" in lines
    assert lines.index("Attempt 1") < lines.index("Attempt 2")
    assert "  Outcome: failed" in lines


def test_the_number_of_tasks_is_not_the_number_of_attempts() -> None:
    """Three tasks and one attempt are told apart in the header."""
    goal = _goal()
    tasks = [_task(goal, f"task {number}") for number in range(3)]

    lines = archived_goal_lines(_entry(goal, tasks, [_record(tasks[0], 1)]))

    assert "Tasks: 3" in lines
    assert lines.count("No attempts recorded.") == 2
