"""Tests for execution coordination."""

from dataclasses import dataclass

from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import (
    EXECUTION_COORDINATION_COMPLETED,
    EXECUTION_COORDINATION_FAILED,
    EXECUTION_COORDINATION_REJECTED,
    ExecutionCoordinateResult,
    ExecutionCoordinator,
)
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
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

    registry = ExecutionAdapterRegistry()
    registry.register(
        "test",
        FakeExecutionAdapter(
            outcome=EXECUTION_OUTCOME_COMPLETED,
            reason="execution completed successfully",
        ),
    )

    coordinator = ExecutionCoordinator(
        adapter_registry=registry,
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
    )

    assert result.task_id == task.id
    assert result.status == EXECUTION_COORDINATION_COMPLETED
    assert result.outcome == EXECUTION_OUTCOME_COMPLETED
    assert result.reason == "execution completed successfully"

    assert (
        TaskRegistry(tmp_path / "tasks.json").get_task(task.id).status
        == TASK_STATUS_COMPLETED
    )


def test_coordinator_records_failed_execution(tmp_path) -> None:
    """A failed adapter outcome fails the task."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)

    registry = ExecutionAdapterRegistry()
    registry.register(
        "test",
        FakeExecutionAdapter(
            outcome=EXECUTION_OUTCOME_FAILED,
            reason="execution adapter reported failure",
        ),
    )

    coordinator = ExecutionCoordinator(
        adapter_registry=registry,
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
    )

    assert result.task_id == task.id
    assert result.status == EXECUTION_COORDINATION_FAILED
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

    registry = ExecutionAdapterRegistry()
    registry.register("test", FailingAdapter())

    coordinator = ExecutionCoordinator(
        adapter_registry=registry,
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
    )

    assert result.status == EXECUTION_COORDINATION_REJECTED
    assert result.outcome is None
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

    registry = ExecutionAdapterRegistry()
    registry.register("test", RecordingAdapter())

    coordinator = ExecutionCoordinator(
        adapter_registry=registry,
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

    coordinator.coordinate(request)

    assert received == [request]


def test_coordinator_does_not_directly_change_outcome(tmp_path) -> None:
    """The coordinator records the adapter's declared outcome."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)

    registry = ExecutionAdapterRegistry()
    registry.register(
        "test",
        FakeExecutionAdapter(
            outcome=EXECUTION_OUTCOME_COMPLETED,
            reason="adapter declared completion",
        ),
    )

    coordinator = ExecutionCoordinator(
        adapter_registry=registry,
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
    )

    assert result.outcome == EXECUTION_OUTCOME_COMPLETED
    assert result.reason == "adapter declared completion"


def test_coordinator_rejects_unknown_execution_target_without_starting(
    tmp_path,
) -> None:
    """An unknown target is rejected before the task enters running."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)

    registry = ExecutionAdapterRegistry()
    registry.register(
        "test",
        FakeExecutionAdapter(
            outcome=EXECUTION_OUTCOME_COMPLETED,
        ),
    )

    coordinator = ExecutionCoordinator(
        adapter_registry=registry,
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

    request = ExecutionRequest(
        task_id=task.id,
        target="missing",
    )

    before = task_registry.get_task(task.id)
    assert before is not None
    assert before.status == TASK_STATUS_READY

    result = coordinator.coordinate(request)

    assert result.task_id == task.id
    assert result.status == EXECUTION_COORDINATION_REJECTED
    assert result.outcome is None
    assert result.reason == "unknown execution target"

    after = task_registry.get_task(task.id)
    assert after is not None
    assert after.status == TASK_STATUS_READY
    assert after.updated_at == before.updated_at


def test_coordinator_records_adapter_exception_as_failed(tmp_path) -> None:
    """An adapter exception fails the running task."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)

    class FailingAdapter:
        def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
            raise RuntimeError("adapter crashed")

    registry = ExecutionAdapterRegistry()
    registry.register("test", FailingAdapter())

    coordinator = ExecutionCoordinator(
        adapter_registry=registry,
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
    )

    assert result.task_id == task.id
    assert result.status == EXECUTION_COORDINATION_FAILED
    assert result.outcome == EXECUTION_OUTCOME_FAILED
    assert result.reason == "execution adapter failed: adapter crashed"

    updated_task = task_registry.get_task(task.id)
    assert updated_task is not None
    assert updated_task.status == TASK_STATUS_FAILED


def test_coordinator_fails_task_when_adapter_returns_wrong_task(
    tmp_path,
) -> None:
    """A mismatched adapter outcome fails the requested task."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)

    class MismatchedAdapter:
        def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
            return ExecutionOutcome(
                task_id="different-task",
                outcome=EXECUTION_OUTCOME_COMPLETED,
            )

    registry = ExecutionAdapterRegistry()
    registry.register("test", MismatchedAdapter())

    coordinator = ExecutionCoordinator(
        adapter_registry=registry,
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
    )

    assert result.task_id == task.id
    assert result.status == EXECUTION_COORDINATION_FAILED
    assert result.outcome == EXECUTION_OUTCOME_FAILED
    assert result.reason == (
        "execution adapter returned outcome for unexpected task"
    )

    updated_task = task_registry.get_task(task.id)
    assert updated_task is not None
    assert updated_task.status == TASK_STATUS_FAILED


def test_coordinator_fails_task_when_adapter_returns_invalid_result(
    tmp_path,
) -> None:
    """An invalid adapter result fails the running task."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)

    class InvalidAdapter:
        def execute(self, request: ExecutionRequest):
            return None

    registry = ExecutionAdapterRegistry()
    registry.register("test", InvalidAdapter())

    coordinator = ExecutionCoordinator(
        adapter_registry=registry,
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
    )

    assert result.task_id == task.id
    assert result.status == EXECUTION_COORDINATION_FAILED
    assert result.outcome == EXECUTION_OUTCOME_FAILED
    assert result.reason == "execution adapter returned invalid outcome"

    updated_task = task_registry.get_task(task.id)
    assert updated_task is not None
    assert updated_task.status == TASK_STATUS_FAILED


def test_execution_coordinate_result_is_immutable():
    """Coordinator results cannot be modified."""
    result = ExecutionCoordinateResult(
        task_id="task-123",
        status=EXECUTION_COORDINATION_COMPLETED,
        outcome=EXECUTION_OUTCOME_COMPLETED,
        reason="completed",
    )

    try:
        result.status = EXECUTION_COORDINATION_FAILED
    except AttributeError:
        pass
    else:
        raise AssertionError("execution coordinate result must be immutable")


def test_execution_coordinate_result_rejects_unknown_status():
    """Coordinator results reject unknown statuses."""
    try:
        ExecutionCoordinateResult(
            task_id="task-123",
            status="running",
            outcome=None,
            reason="invalid",
        )
    except ValueError as exc:
        assert str(exc) == "unknown execution coordination status: running"
    else:
        raise AssertionError("unknown status must be rejected")


def _coordinator_for(goal_registry, task_registry, adapter):
    """Build a coordinator whose registries all live under tmp_path."""
    registry = ExecutionAdapterRegistry()
    registry.register("test", adapter)

    return ExecutionCoordinator(
        adapter_registry=registry,
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


def test_coordinator_records_one_attempt_for_a_completed_task(
    tmp_path,
) -> None:
    """A whole run leaves one closed attempt with its start and reason."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)
    coordinator = _coordinator_for(
        goal_registry,
        task_registry,
        FakeExecutionAdapter(
            outcome=EXECUTION_OUTCOME_COMPLETED,
            reason="execution completed successfully",
        ),
    )

    coordinator.coordinate(ExecutionRequest(task_id=task.id, target="test"))

    records = ExecutionRecordRegistry(
        tmp_path / "executions.json",
    ).list_attempts(task.id)

    assert len(records) == 1
    assert records[0].source == "coordinator"
    assert records[0].target == "test"
    assert records[0].started_at is not None
    assert records[0].ended_as == "completed"
    assert records[0].reason == "execution completed successfully"


def test_coordinator_keeps_the_adapter_failure_reason(tmp_path) -> None:
    """An adapter exception is stored as the reason the attempt failed."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)

    class FailingAdapter:
        def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
            raise RuntimeError("adapter crashed")

    coordinator = _coordinator_for(
        goal_registry,
        task_registry,
        FailingAdapter(),
    )

    coordinator.coordinate(ExecutionRequest(task_id=task.id, target="test"))

    records = ExecutionRecordRegistry(
        tmp_path / "executions.json",
    ).list_attempts(task.id)

    assert len(records) == 1
    assert records[0].ended_as == "failed"
    assert records[0].reason == "execution adapter failed: adapter crashed"


def test_coordinator_writes_no_record_for_an_unknown_target(
    tmp_path,
) -> None:
    """A request rejected before it starts leaves no attempt behind."""
    goal_registry, task_registry, task = make_ready_task(tmp_path)
    coordinator = _coordinator_for(
        goal_registry,
        task_registry,
        FakeExecutionAdapter(outcome=EXECUTION_OUTCOME_COMPLETED),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="unknown"),
    )

    assert result.status == EXECUTION_COORDINATION_REJECTED
    assert not (tmp_path / "executions.json").exists()
