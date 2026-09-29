"""Tests for execution coordination."""

from dataclasses import dataclass

from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import (
    ExecutionCoordinator,
    ExecutionAdapter,
)
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator

from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_COMPLETED,
    EXECUTION_OUTCOME_FAILED,
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
)
from aic_control_centre.execution.start import ExecutionStarter
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.model import (
    TASK_STATUS_READY,
    TASK_STATUS_RUNNING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry


@dataclass
class FakeExecutionAdapter:
    outcome: str
    reason: str = ""

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        return ExecutionOutcome(
            task_id=request.task_id,
            outcome=self.outcome,
            reason=self.reason,
        )


def make_ready_task(tmp_path):
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Coordinator goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Coordinator task",
    )
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, TASK_STATUS_READY)

    return goal_registry, task_registry, task


def test_coordinator_completes_started_task(tmp_path) -> None:
    """A successful adapter outcome completes the task."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)

    coordinator = ExecutionCoordinator(
        starter=ExecutionStarter(
            admission=ExecutionAdmission(
                readiness_evaluator=TaskReadinessEvaluator(
                    goal_registry=goal_registry,
                    task_registry=task_registry,
                )
            ),
            task_registry=task_registry,
        ),
        outcome_recorder=ExecutionOutcomeRecorder(
            task_registry=task_registry,
            goal_registry=goal_registry,
        ),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="test"),
        FakeExecutionAdapter(
            outcome=EXECUTION_OUTCOME_COMPLETED,
            reason="execution completed successfully",
        ),
    )

    assert result.task_id == task.id
    assert result.completed is True
    assert result.outcome == EXECUTION_OUTCOME_COMPLETED
    assert result.reason == "execution completed successfully"

    assert (
        TaskRegistry(tmp_path / "tasks.json").get_task(task.id).status
        == TASK_STATUS_COMPLETED
    )


def test_coordinator_records_failed_execution(tmp_path) -> None:
    """A failed adapter outcome fails the task."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)

    coordinator = ExecutionCoordinator(
        starter=ExecutionStarter(
            admission=ExecutionAdmission(
                readiness_evaluator=TaskReadinessEvaluator(
                    goal_registry=goal_registry,
                    task_registry=task_registry,
                )
            ),
            task_registry=task_registry,
        ),
        outcome_recorder=ExecutionOutcomeRecorder(
            task_registry=task_registry,
            goal_registry=goal_registry,
        ),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="test"),
        FakeExecutionAdapter(
            outcome=EXECUTION_OUTCOME_FAILED,
            reason="execution adapter reported failure",
        ),
    )

    assert result.task_id == task.id
    assert result.completed is True
    assert result.outcome == EXECUTION_OUTCOME_FAILED
    assert result.reason == "execution adapter reported failure"

    assert (
        TaskRegistry(tmp_path / "tasks.json").get_task(task.id).status
        == TASK_STATUS_FAILED
    )


def test_coordinator_does_not_execute_rejected_task(tmp_path) -> None:
    """A task rejected by admission never reaches the adapter."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Rejected coordinator goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Not ready",
    )
    task_registry.add_task(task)

    class FailingAdapter:
        def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
            raise AssertionError("adapter must not execute rejected task")

    coordinator = ExecutionCoordinator(
        starter=ExecutionStarter(
            admission=ExecutionAdmission(
                readiness_evaluator=TaskReadinessEvaluator(
                    goal_registry=goal_registry,
                    task_registry=task_registry,
                )
            ),
            task_registry=task_registry,
        ),
        outcome_recorder=ExecutionOutcomeRecorder(
            task_registry=task_registry,
            goal_registry=goal_registry,
        ),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="test"),
        FailingAdapter(),
    )

    assert result.started is False
    assert result.reason == "task status is pending"

    assert (
        TaskRegistry(tmp_path / "tasks.json").get_task(task.id).status
        != TASK_STATUS_RUNNING
    )


def test_coordinator_passes_request_to_adapter(tmp_path) -> None:
    """The coordinator gives the original request to the adapter."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)

    received = []

    class RecordingAdapter:
        def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
            received.append(request)

            return ExecutionOutcome(
                task_id=request.task_id,
                outcome=EXECUTION_OUTCOME_COMPLETED,
            )

    coordinator = ExecutionCoordinator(
        starter=ExecutionStarter(
            admission=ExecutionAdmission(
                readiness_evaluator=TaskReadinessEvaluator(
                    goal_registry=goal_registry,
                    task_registry=task_registry,
                )
            ),
            task_registry=task_registry,
        ),
        outcome_recorder=ExecutionOutcomeRecorder(
            task_registry=task_registry,
            goal_registry=goal_registry,
        ),
    )

    request = ExecutionRequest(task_id=task.id, target="test")

    coordinator.coordinate(request, RecordingAdapter())

    assert received == [request]


def test_coordinator_does_not_directly_change_outcome(tmp_path) -> None:
    """The coordinator records the adapter's declared outcome."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)

    coordinator = ExecutionCoordinator(
        starter=ExecutionStarter(
            admission=ExecutionAdmission(
                readiness_evaluator=TaskReadinessEvaluator(
                    goal_registry=goal_registry,
                    task_registry=task_registry,
                )
            ),
            task_registry=task_registry,
        ),
        outcome_recorder=ExecutionOutcomeRecorder(
            task_registry=task_registry,
            goal_registry=goal_registry,
        ),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="test"),
        FakeExecutionAdapter(
            outcome=EXECUTION_OUTCOME_COMPLETED,
            reason="adapter declared completion",
        ),
    )

    assert result.outcome == EXECUTION_OUTCOME_COMPLETED
    assert result.reason == "adapter declared completion"
