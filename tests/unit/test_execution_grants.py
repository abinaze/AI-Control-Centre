"""Tests for the grants that let a project use an execution target."""

import pytest

from aic_control_centre.execution.adapters import NoopAdapter
from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import ExecutionCoordinator
from aic_control_centre.execution.outcome import (
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
)
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.start import (
    ExecutionStarter,
    ExecutionStartResult,
)
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


class SpyStarter:
    """A starter that records the requests it is given and starts nothing."""

    def __init__(self):
        self.requests = []

    def start(self, request):
        self.requests.append(request)

        return ExecutionStartResult(
            task_id=request.task_id,
            started=False,
            reason="spy",
        )


class PlainAdapter:
    """An adapter that says nothing about grants."""

    def execute(self, request):
        raise AssertionError("the spy never starts a run")


class NeedsGrantAdapter(PlainAdapter):
    requires_grant = True


class NoGrantNeededAdapter(PlainAdapter):
    requires_grant = False


def _coordinator(adapter):
    adapters = ExecutionAdapterRegistry()
    adapters.register("target", adapter)
    spy = SpyStarter()
    coordinator = ExecutionCoordinator(
        adapter_registry=adapters,
        starter=spy,
        outcome_recorder=object(),
    )

    return coordinator, spy


@pytest.mark.parametrize(
    ("adapter", "expected"),
    [
        (NoopAdapter(), False),
        (NoGrantNeededAdapter(), False),
        (NeedsGrantAdapter(), True),
        (PlainAdapter(), True),
    ],
)
def test_coordinator_sends_the_request_marked_by_the_adapter(
    adapter,
    expected,
) -> None:
    """An adapter that says nothing is treated as needing a grant."""
    coordinator, spy = _coordinator(adapter)

    coordinator.coordinate(ExecutionRequest(task_id="task-1", target="target"))

    assert [request.requires_grant for request in spy.requests] == [expected]


@pytest.mark.parametrize(
    ("adapter", "asked", "expected"),
    [
        (PlainAdapter(), False, True),
        (NoGrantNeededAdapter(), True, False),
    ],
)
def test_the_adapter_decides_not_the_caller(adapter, asked, expected) -> None:
    """A caller cannot switch off the check for an adapter that needs it."""
    coordinator, spy = _coordinator(adapter)

    coordinator.coordinate(
        ExecutionRequest(
            task_id="task-1",
            target="target",
            requires_grant=asked,
        ),
    )

    assert [request.requires_grant for request in spy.requests] == [expected]


class InMemoryGrants:
    """A grant source that holds its grants in memory."""

    def __init__(self, *granted):
        self.granted = set(granted)

    def is_granted(self, project, target):
        return (project, target) in self.granted


class CompletingAdapter:
    """An adapter that completes the task. It needs a grant."""

    def execute(self, request):
        return ExecutionOutcome(
            task_id=request.task_id,
            outcome="completed",
            reason="done",
        )


def _make_task(tmp_path, project="alpha", status="ready"):
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")
    goal = Goal.create(description="Granted goal", project=project)
    goal_registry.add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Granted task")
    task_registry.add_task(task)

    if status != "pending":
        task_registry.update_task_status(task.id, status)

    evaluator = TaskReadinessEvaluator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    )

    return evaluator, goal_registry, task_registry, task


def _request(task, target="shell"):
    return ExecutionRequest(task_id=task.id, target=target)


def test_a_request_is_refused_when_no_grant_covers_it(tmp_path) -> None:
    """With nothing granted, a target that needs a grant is refused."""
    evaluator, _, _, task = _make_task(tmp_path)
    admission = ExecutionAdmission(evaluator, InMemoryGrants())

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert result.reason == "target shell is not granted for project alpha"


def test_a_grant_for_the_project_and_target_allows_the_request(
    tmp_path,
) -> None:
    """The grant is for one project and one target, and it works."""
    evaluator, _, _, task = _make_task(tmp_path)
    admission = ExecutionAdmission(
        evaluator,
        InMemoryGrants(("alpha", "shell")),
    )

    assert admission.evaluate(_request(task)).accepted is True


def test_a_grant_for_another_project_does_not_allow_it(tmp_path) -> None:
    """Allowing one project does not allow another."""
    evaluator, _, _, task = _make_task(tmp_path, project="alpha")
    admission = ExecutionAdmission(
        evaluator,
        InMemoryGrants(("beta", "shell")),
    )

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert "project alpha" in result.reason


def test_a_grant_for_another_target_does_not_allow_it(tmp_path) -> None:
    """Allowing one target does not allow another."""
    evaluator, _, _, task = _make_task(tmp_path)
    admission = ExecutionAdmission(
        evaluator,
        InMemoryGrants(("alpha", "other")),
    )

    assert admission.evaluate(_request(task)).accepted is False


def test_a_request_that_needs_no_grant_is_allowed_without_one(
    tmp_path,
) -> None:
    """A target that does nothing needs no permission."""
    evaluator, _, _, task = _make_task(tmp_path)
    admission = ExecutionAdmission(evaluator, InMemoryGrants())
    request = ExecutionRequest(
        task_id=task.id,
        target="noop",
        requires_grant=False,
    )

    assert admission.evaluate(request).accepted is True


def test_admission_with_no_grant_source_refuses_by_default(tmp_path) -> None:
    """Nothing is allowed unless a source says so."""
    evaluator, _, _, task = _make_task(tmp_path)

    result = ExecutionAdmission(evaluator).evaluate(_request(task))

    assert result.accepted is False
    assert "not granted" in result.reason


def test_readiness_is_checked_before_grants(tmp_path) -> None:
    """A task that is not ready is refused for that reason."""
    evaluator, _, _, task = _make_task(tmp_path, status="pending")
    admission = ExecutionAdmission(
        evaluator,
        InMemoryGrants(("alpha", "shell")),
    )

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert "not granted" not in result.reason


def test_a_revoked_grant_stops_the_next_request(tmp_path) -> None:
    """Taking a grant away takes effect at the next check."""
    evaluator, _, _, task = _make_task(tmp_path)
    grants = InMemoryGrants(("alpha", "shell"))
    admission = ExecutionAdmission(evaluator, grants)

    assert admission.evaluate(_request(task)).accepted is True

    grants.granted.clear()

    assert admission.evaluate(_request(task)).accepted is False


def test_a_refused_start_writes_nothing(tmp_path) -> None:
    """A request without a grant opens no attempt and moves no task."""
    evaluator, _, task_registry, task = _make_task(tmp_path)
    starter = ExecutionStarter(
        admission=ExecutionAdmission(evaluator, InMemoryGrants()),
        task_registry=task_registry,
    )

    result = starter.start(_request(task))

    assert result.started is False
    assert result.attempt_id is None
    assert not (tmp_path / "executions.json").exists()
    assert task_registry.get_task(task.id).status == "ready"


def _coordinator_with(tmp_path, grants):
    evaluator, goal_registry, task_registry, task = _make_task(tmp_path)
    adapters = ExecutionAdapterRegistry()
    adapters.register("shell", CompletingAdapter())
    coordinator = ExecutionCoordinator(
        adapter_registry=adapters,
        starter=ExecutionStarter(
            admission=ExecutionAdmission(evaluator, grants),
            task_registry=task_registry,
        ),
        outcome_recorder=ExecutionOutcomeRecorder(
            task_registry=task_registry,
            goal_registry=goal_registry,
        ),
    )

    return coordinator, task_registry, task


def test_the_coordinator_rejects_a_target_that_is_not_granted(
    tmp_path,
) -> None:
    """The refusal reaches the caller, and the adapter never runs."""
    coordinator, task_registry, task = _coordinator_with(
        tmp_path,
        InMemoryGrants(),
    )

    result = coordinator.coordinate(_request(task))

    assert result.status == "rejected"
    assert "not granted for project alpha" in result.reason
    assert task_registry.get_task(task.id).status == "ready"
    assert not (tmp_path / "executions.json").exists()


def test_the_coordinator_runs_a_target_that_is_granted(tmp_path) -> None:
    """With the grant in place the whole run completes."""
    coordinator, task_registry, task = _coordinator_with(
        tmp_path,
        InMemoryGrants(("alpha", "shell")),
    )

    result = coordinator.coordinate(_request(task))

    assert result.status == "completed"
    assert task_registry.get_task(task.id).status == "completed"
