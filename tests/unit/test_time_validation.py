"""Tests for time checks in goal task validation."""

from dataclasses import asdict

import pytest

from aic_control_centre.execution.records import (
    ExecutionRecord,
    ExecutionRecordRegistry,
)
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.permissions.model import Grant
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.validation.goal_tasks import GoalTaskValidator

GOOD = "2026-10-19T09:00:00+00:00"


def _goal(**changes):
    values = {
        "id": "goal-1",
        "description": "A goal",
        "project": "alpha",
        "status": "in_progress",
        "created_at": GOOD,
        "updated_at": GOOD,
    }
    values.update(changes)

    return Goal(**values)


def _task(**changes):
    values = {
        "id": "task-1",
        "goal_id": "goal-1",
        "title": "A task",
        "description": "",
        "status": "running",
        "created_at": GOOD,
        "updated_at": GOOD,
    }
    values.update(changes)

    return Task(**values)


def _record(**changes):
    values = {
        "id": "record-1",
        "task_id": "task-1",
        "source": "cli",
        "target": None,
        "started_at": GOOD,
        "ended_at": None,
        "ended_as": None,
        "reason": "",
    }
    values.update(changes)

    return ExecutionRecord(**values)


def _grant(**changes):
    values = {
        "id": "grant-1",
        "project": "alpha",
        "target": "noop",
        "granted_at": GOOD,
        "reason": "trusted",
        "revoked_at": None,
    }
    values.update(changes)

    return Grant(**values)


def _write(tmp_path, name, key, items):
    write_text_atomic(
        tmp_path / name,
        serialize_state_items(key, [asdict(item) for item in items]),
    )


def _validate(
    tmp_path,
    goal=None,
    task=None,
    records=None,
    grants=None,
    check_records=False,
    check_grants=False,
):
    """Validate a state of one goal and one running task."""
    _write(tmp_path, "goals.json", "goals", [goal or _goal()])
    _write(tmp_path, "tasks.json", "tasks", [task or _task()])

    if records is not None:
        _write(tmp_path, "executions.json", "executions", records)

    if grants is not None:
        _write(tmp_path, "permissions.json", "permissions", grants)

    validator = GoalTaskValidator(
        goal_registry=GoalRegistry(tmp_path / "goals.json"),
        task_registry=TaskRegistry(tmp_path / "tasks.json"),
        record_registry=(
            ExecutionRecordRegistry(tmp_path / "executions.json")
            if check_records
            else None
        ),
        permission_registry=(
            PermissionRegistry(tmp_path / "permissions.json")
            if check_grants
            else None
        ),
    )

    return validator.validate()


def test_a_state_with_readable_times_is_valid(tmp_path) -> None:
    """The times that the registries write are accepted."""
    result = _validate(
        tmp_path,
        records=[_record()],
        grants=[_grant()],
        check_records=True,
        check_grants=True,
    )

    assert result.valid is True


@pytest.mark.parametrize(
    "value",
    ["2026-10-19T14:00:00+05:00", "2026-10-19T09:00:00Z"],
)
def test_other_offsets_are_accepted(tmp_path, value) -> None:
    """A time does not have to be written in UTC."""
    result = _validate(
        tmp_path,
        goal=_goal(created_at=value),
        task=_task(updated_at=value),
    )

    assert result.valid is True


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
def test_a_goal_time_that_cannot_be_read_is_reported(
    tmp_path,
    field,
) -> None:
    """Both times of a goal are checked."""
    result = _validate(tmp_path, goal=_goal(**{field: "garbage"}))

    assert result.errors == (
        f"Goal goal-1 has a time that cannot be read in {field}: 'garbage'",
    )


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
def test_a_task_time_that_cannot_be_read_is_reported(
    tmp_path,
    field,
) -> None:
    """Both times of a task are checked."""
    result = _validate(tmp_path, task=_task(**{field: "garbage"}))

    assert result.errors == (
        f"Task task-1 has a time that cannot be read in {field}: 'garbage'",
    )


@pytest.mark.parametrize(
    "value",
    ["2026-10-19", "2026-10-19T09:00:00", "not a time", "", None, 5],
)
def test_a_time_with_no_offset_or_no_text_is_reported(
    tmp_path,
    value,
) -> None:
    """A bare date, a time with no offset, an empty or a non-text value."""
    result = _validate(tmp_path, task=_task(updated_at=value))

    assert result.errors == (
        "Task task-1 has a time that cannot be read in updated_at: "
        f"{value!r}",
    )


@pytest.mark.parametrize("field", ["started_at", "ended_at"])
def test_a_record_time_that_cannot_be_read_is_reported(
    tmp_path,
    field,
) -> None:
    """Both times of an execution record are checked."""
    values = {
        "ended_at": "2026-10-19T10:00:00+00:00",
        "ended_as": "completed",
    }
    values[field] = "garbage"

    record = _record(**values)

    result = _validate(tmp_path, records=[record], check_records=True)

    assert (
        f"Execution record record-1 has a time that cannot be read in "
        f"{field}: 'garbage'"
    ) in result.errors


def test_an_open_attempt_may_have_no_end_time(tmp_path) -> None:
    """An empty end time is the normal state of an open attempt."""
    result = _validate(
        tmp_path,
        records=[_record(ended_at=None)],
        check_records=True,
    )

    assert result.valid is True


def test_a_closed_legacy_attempt_may_have_no_start_time(tmp_path) -> None:
    """A record made before start times existed has none."""
    record = _record(
        started_at=None,
        ended_at="2026-10-19T10:00:00+00:00",
        ended_as="completed",
    )

    result = _validate(
        tmp_path,
        task=_task(status="completed"),
        goal=_goal(status="completed"),
        records=[record],
        check_records=True,
    )

    assert result.valid is True


@pytest.mark.parametrize("field", ["granted_at", "revoked_at"])
def test_a_grant_time_that_cannot_be_read_is_reported(
    tmp_path,
    field,
) -> None:
    """Both times of a grant are checked."""
    values = {"granted_at": GOOD, "revoked_at": "2026-10-20T00:00:00+00:00"}
    values[field] = "garbage"

    result = _validate(
        tmp_path,
        grants=[_grant(**values)],
        check_grants=True,
    )

    assert (
        f"Grant grant-1 has a time that cannot be read in {field}: "
        "'garbage'"
    ) in result.errors


def test_an_active_grant_may_have_no_revoke_time(tmp_path) -> None:
    """An empty revoke time means the grant is still active."""
    result = _validate(
        tmp_path,
        grants=[_grant(revoked_at=None)],
        check_grants=True,
    )

    assert result.valid is True


def test_records_and_grants_are_checked_only_when_given(tmp_path) -> None:
    """Without their registries their files are left alone."""
    result = _validate(
        tmp_path,
        records=[_record(started_at="garbage")],
        grants=[_grant(granted_at="garbage")],
    )

    assert result.valid is True


def test_every_unreadable_time_is_reported_together(tmp_path) -> None:
    """One run lists all of them."""
    result = _validate(
        tmp_path,
        goal=_goal(created_at="x", updated_at="y"),
        task=_task(created_at="z"),
        records=[_record(started_at="w")],
        grants=[_grant(granted_at="v")],
        check_records=True,
        check_grants=True,
    )

    assert len(result.errors) == 5


def test_a_long_value_is_shortened_in_the_message(tmp_path) -> None:
    """A huge value does not flood the report."""
    result = _validate(tmp_path, task=_task(updated_at="x" * 500))

    [message] = result.errors

    assert len(message) < 150
    assert message.endswith("...")


def test_checking_times_never_writes(tmp_path) -> None:
    """Validation only reads."""
    _validate(
        tmp_path,
        task=_task(updated_at="garbage"),
        records=[_record(started_at="garbage")],
        grants=[_grant(granted_at="garbage")],
        check_records=True,
        check_grants=True,
    )
    names = ("goals.json", "tasks.json", "executions.json", "permissions.json")
    before = {name: (tmp_path / name).read_bytes() for name in names}

    GoalTaskValidator(
        goal_registry=GoalRegistry(tmp_path / "goals.json"),
        task_registry=TaskRegistry(tmp_path / "tasks.json"),
        record_registry=ExecutionRecordRegistry(tmp_path / "executions.json"),
        permission_registry=PermissionRegistry(tmp_path / "permissions.json"),
    ).validate()

    assert {name: (tmp_path / name).read_bytes() for name in names} == before
