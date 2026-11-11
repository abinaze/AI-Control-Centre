"""Tests for the lines that show one execution attempt."""

from aic_control_centre.execution.history import attempt_lines
from aic_control_centre.execution.records import ExecutionRecord

START = "2026-10-30T00:00:00+00:00"
END = "2026-10-30T00:00:01+00:00"


def _record(**fields):
    values = {
        "id": "record",
        "task_id": "task",
        "source": "coordinator",
        "target": "noop",
        "started_at": START,
        "ended_at": END,
        "ended_as": "completed",
        "reason": "",
    }
    values.update(fields)

    return ExecutionRecord(**values)


def test_a_closed_attempt_has_route_times_outcome_and_reason() -> None:
    """The first line is blank, and the number is the one that was given."""
    lines = attempt_lines(3, _record(reason="done"), "completed")

    assert lines == [
        "",
        "Attempt 3",
        "  Route: coordinator (noop)",
        f"  Started: {START}",
        f"  Ended: {END}",
        "  Outcome: completed",
        "  Reason: done",
    ]


def test_a_route_without_a_target_is_the_source_alone() -> None:
    """There are no brackets when nothing was targeted."""
    lines = attempt_lines(1, _record(source="cli", target=None), "failed")

    assert "  Route: cli" in lines
    assert not any("(" in line for line in lines)


def test_an_empty_reason_has_no_line() -> None:
    """The reason line is left out, not printed empty."""
    lines = attempt_lines(1, _record(reason=""), "completed")

    assert not any(line.startswith("  Reason") for line in lines)


def test_a_failed_attempt_shows_its_outcome() -> None:
    """The outcome is the one that the record ended as."""
    lines = attempt_lines(1, _record(ended_as="failed"), "failed")

    assert "  Outcome: failed" in lines


def test_a_record_with_no_start_says_that_it_is_unknown() -> None:
    """Records from before the start was kept have no time."""
    lines = attempt_lines(1, _record(started_at=None), "completed")

    assert "  Started: unknown (before records existed)" in lines


def test_an_open_attempt_of_a_running_task_has_no_note() -> None:
    """It is open because the task is running."""
    lines = attempt_lines(
        2,
        _record(ended_at=None, ended_as=None),
        "running",
    )

    assert lines[-1] == "  Ended: still open"
    assert not any(line.startswith("  Note") for line in lines)
    assert not any(line.startswith("  Outcome") for line in lines)


def test_an_open_attempt_of_a_task_that_is_not_running_has_a_note() -> None:
    """It was left open, and the lines say so."""
    note = "  Note: the task is not running, so this attempt was left open"

    for status in ("pending", "ready"):
        lines = attempt_lines(
            2,
            _record(ended_at=None, ended_as=None),
            status,
        )

        assert lines[-2:] == ["  Ended: still open", note]

    for status in ("completed", "failed"):
        lines = attempt_lines(
            2,
            _record(ended_at=None, ended_as=None),
            status,
        )

        assert "  Ended: still open" in lines
        assert note in lines


def test_the_lines_are_returned_and_nothing_is_printed(capsys) -> None:
    """Whoever calls it decides where the lines go."""
    attempt_lines(1, _record(), "completed")

    assert capsys.readouterr().out == ""


def test_an_open_attempt_of_a_final_task_says_how_to_close_it() -> None:
    """The line names the task of the record, and the command to use."""
    for status in ("completed", "failed"):
        lines = attempt_lines(
            2,
            _record(task_id="the-task", ended_at=None, ended_as=None),
            status,
        )

        assert lines[-3:] == [
            "  Ended: still open",
            "  Note: the task is not running, "
            "so this attempt was left open",
            "  Close it with: aic task close-attempt the-task "
            '--reason "<text>"',
        ]


def test_the_other_open_attempts_have_no_close_line() -> None:
    """A task that is not final is not closed with that command."""
    for status in ("pending", "ready", "running"):
        lines = attempt_lines(
            2,
            _record(ended_at=None, ended_as=None),
            status,
        )

        assert not any("close-attempt" in line for line in lines)


def test_a_closed_attempt_of_a_final_task_has_no_close_line() -> None:
    """There is nothing to close."""
    for status in ("completed", "failed"):
        lines = attempt_lines(1, _record(reason="done"), status)

        assert not any("close-attempt" in line for line in lines)
