"""Tests for a run that is superseded while its adapter is still running.

A person can requeue and restart a task while an adapter works on it. The
adapter's late outcome must not change the newer attempt.
"""

import pytest

from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import ExecutionCoordinator
from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_COMPLETED,
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
)
from aic_control_centre.execution.records import (
    EXECUTION_SOURCE_CLI,
    EXECUTION_SOURCE_COORDINATOR,
    ExecutionRecordRegistry,
)
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.start import ExecutionStarter
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.tasks.commands import requeue_task, start_task
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


class OperatorDuringRun:
    """An adapter that lets a person act on the task while it runs."""

    def __init__(self, actions, behavior="completed"):
        self.actions = actions
        self.behavior = behavior

    def execute(self, request):
        for action in self.actions:
            assert action(request.task_id) == 0

        if self.behavior == "raises":
            raise RuntimeError("boom")

        if self.behavior == "invalid":
            return "not an outcome"

        task_id = request.task_id

        if self.behavior == "wrong task":
            task_id = "some-other-task"

        return ExecutionOutcome(
            task_id=task_id,
            outcome=EXECUTION_OUTCOME_COMPLETED,
            reason="adapter finished",
        )


def _requeue(task_id):
    """Do what a person does when a run looks dead."""
    return requeue_task(task_id, "looks dead")


def _setup(tmp_path, monkeypatch, adapter):
    """Build a coordinator and a ready task in shared registries."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")
    goal = Goal.create(description="Superseded goal", project="TestProject")
    goal_registry.add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Superseded task")
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, "ready")

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.GoalRegistry",
        lambda: goal_registry,
    )
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.TaskRegistry",
        lambda: task_registry,
    )

    adapters = ExecutionAdapterRegistry()
    adapters.register("slow", adapter)
    coordinator = ExecutionCoordinator(
        adapter_registry=adapters,
        starter=ExecutionStarter(
            admission=ExecutionAdmission(
                readiness_evaluator=TaskReadinessEvaluator(
                    goal_registry=goal_registry,
                    task_registry=task_registry,
                ),
            ),
            task_registry=task_registry,
        ),
        outcome_recorder=ExecutionOutcomeRecorder(
            task_registry=task_registry,
            goal_registry=goal_registry,
        ),
    )
    records = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")

    return coordinator, task, task_registry, records


@pytest.mark.parametrize(
    ("behavior", "reported"),
    [
        ("completed", "completed: adapter finished"),
        ("raises", "failed: execution adapter failed: boom"),
        ("invalid", "failed: execution adapter returned invalid outcome"),
        (
            "wrong task",
            "failed: execution adapter returned outcome for unexpected task",
        ),
    ],
)
def test_late_outcome_does_not_change_a_newer_attempt(
    tmp_path,
    monkeypatch,
    behavior,
    reported,
) -> None:
    """A run superseded by a requeue and a restart cannot close the new one."""
    coordinator, task, task_registry, records = _setup(
        tmp_path,
        monkeypatch,
        OperatorDuringRun([_requeue, start_task], behavior),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="slow"),
    )

    attempts = records.list_attempts(task.id)

    assert result.status == "rejected"
    assert "superseded" in result.reason
    assert reported in result.reason
    assert task_registry.get_task(task.id).status == "running"
    assert len(attempts) == 2
    assert attempts[0].ended_as == "requeued"
    assert attempts[0].source == EXECUTION_SOURCE_COORDINATOR
    assert attempts[1].is_open
    assert attempts[1].source == EXECUTION_SOURCE_CLI
    assert attempts[1].reason == ""


def test_outcome_after_a_requeue_alone_is_refused(
    tmp_path,
    monkeypatch,
) -> None:
    """With no restart the task is ready, so the outcome is refused."""
    coordinator, task, task_registry, records = _setup(
        tmp_path,
        monkeypatch,
        OperatorDuringRun([_requeue]),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="slow"),
    )

    assert result.status == "rejected"
    assert result.reason == "task status is ready"
    assert task_registry.get_task(task.id).status == "ready"
    assert [a.ended_as for a in records.list_attempts(task.id)] == [
        "requeued",
    ]


def test_run_that_is_not_superseded_closes_its_own_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    """Without interference the outcome is recorded as before."""
    coordinator, task, task_registry, records = _setup(
        tmp_path,
        monkeypatch,
        OperatorDuringRun([]),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="slow"),
    )

    attempts = records.list_attempts(task.id)

    assert result.status == "completed"
    assert task_registry.get_task(task.id).status == "completed"
    assert len(attempts) == 1
    assert attempts[0].ended_as == "completed"
    assert attempts[0].source == EXECUTION_SOURCE_COORDINATOR
    assert records.get_open_attempt(task.id) is None
