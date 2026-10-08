"""Parity tests: the CLI and the library record attempts alike.

Two routes can start a task and two can end it. These tests run both
routes against the same registries and require the records to have the
same shape, so one route cannot quietly stop recording.
"""

import pytest

from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_COMPLETED,
    EXECUTION_OUTCOME_FAILED,
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
)
from aic_control_centre.execution.records import (
    ABANDONED_REASON,
    EXECUTION_SOURCE_CLI,
    EXECUTION_SOURCE_COORDINATOR,
    ExecutionRecordRegistry,
)
from aic_control_centre.execution.start import ExecutionStarter
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.tasks.commands import (
    complete_task,
    fail_task,
    start_task,
)
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


def _shape(record) -> tuple:
    """Return the parts of a record that must not depend on the route."""
    return (
        record.started_at is not None,
        record.ended_at is not None,
        record.ended_as,
        record.reason,
    )


def _setup(tmp_path, monkeypatch):
    """Build two ready tasks, one for each route, in shared registries."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")
    goal = Goal.create(description="Parity goal", project="TestProject")
    goal_registry.add_goal(goal)

    tasks = []

    for title in ("CLI task", "Library task"):
        task = Task.create(goal_id=goal.id, title=title)
        task_registry.add_task(task)
        task_registry.update_task_status(task.id, "ready")
        tasks.append(task)

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.GoalRegistry",
        lambda: goal_registry,
    )
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: task_registry,
    )

    starter = ExecutionStarter(
        admission=ExecutionAdmission(
            readiness_evaluator=TaskReadinessEvaluator(
                goal_registry=goal_registry,
                task_registry=task_registry,
            ),
        ),
        task_registry=task_registry,
    )
    recorder = ExecutionOutcomeRecorder(
        task_registry=task_registry,
        goal_registry=goal_registry,
    )
    records = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")

    return tasks[0], tasks[1], starter, recorder, records


@pytest.mark.parametrize(
    ("cli_finish", "outcome"),
    [
        (complete_task, EXECUTION_OUTCOME_COMPLETED),
        (fail_task, EXECUTION_OUTCOME_FAILED),
    ],
)
def test_cli_and_library_record_an_attempt_alike(
    tmp_path,
    monkeypatch,
    cli_finish,
    outcome,
) -> None:
    """Both routes open and close an attempt with the same shape."""
    cli_task, library_task, starter, recorder, records = _setup(
        tmp_path,
        monkeypatch,
    )

    assert start_task(cli_task.id) == 0
    starter.start(ExecutionRequest(task_id=library_task.id, target="test"))

    opened_cli = records.list_attempts(cli_task.id)
    opened_library = records.list_attempts(library_task.id)

    assert len(opened_cli) == len(opened_library) == 1
    assert _shape(opened_cli[0]) == _shape(opened_library[0])
    assert opened_cli[0].is_open and opened_library[0].is_open

    assert cli_finish(cli_task.id) == 0
    recorder.record(ExecutionOutcome(task_id=library_task.id, outcome=outcome))

    closed_cli = records.list_attempts(cli_task.id)
    closed_library = records.list_attempts(library_task.id)

    assert len(closed_cli) == len(closed_library) == 1
    assert _shape(closed_cli[0]) == _shape(closed_library[0])
    assert closed_cli[0].ended_as == outcome
    assert records.get_open_attempt(cli_task.id) is None
    assert records.get_open_attempt(library_task.id) is None


def test_only_the_route_and_target_differ_between_routes(
    tmp_path,
    monkeypatch,
) -> None:
    """The route and the target are the only fields that may differ."""
    cli_task, library_task, starter, _, records = _setup(
        tmp_path,
        monkeypatch,
    )

    assert start_task(cli_task.id) == 0
    starter.start(ExecutionRequest(task_id=library_task.id, target="test"))

    cli_record = records.list_attempts(cli_task.id)[0]
    library_record = records.list_attempts(library_task.id)[0]

    assert (cli_record.source, cli_record.target) == (
        EXECUTION_SOURCE_CLI,
        None,
    )
    assert (library_record.source, library_record.target) == (
        EXECUTION_SOURCE_COORDINATOR,
        "test",
    )


def test_cli_and_library_abandon_a_stale_attempt_alike(
    tmp_path,
    monkeypatch,
) -> None:
    """Both routes close a left-over open record the same way."""
    cli_task, library_task, starter, _, records = _setup(
        tmp_path,
        monkeypatch,
    )
    records.open_attempt(cli_task.id, EXECUTION_SOURCE_CLI)
    records.open_attempt(library_task.id, EXECUTION_SOURCE_CLI)

    assert start_task(cli_task.id) == 0
    starter.start(ExecutionRequest(task_id=library_task.id, target="test"))

    cli_records = records.list_attempts(cli_task.id)
    library_records = records.list_attempts(library_task.id)

    assert [_shape(record) for record in cli_records] == [
        _shape(record) for record in library_records
    ]
    assert cli_records[0].reason == ABANDONED_REASON
    assert cli_records[1].is_open and library_records[1].is_open
