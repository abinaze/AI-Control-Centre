"""Tests for the coordinator's state guard."""

import os
import subprocess
import sys
from contextlib import contextmanager

import pytest

from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import ExecutionCoordinator
from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_COMPLETED,
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
)
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.start import ExecutionStarter
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.locking import state_lock
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


class Journal:
    """Record when the guard is entered and left, and when the adapter runs."""

    def __init__(self):
        self.events = []

    @contextmanager
    def guard(self):
        self.events.append("enter")

        try:
            yield
        finally:
            self.events.append("exit")


class JournalAdapter:
    """An adapter that writes to the journal and then behaves as told."""

    requires_grant = False

    def __init__(self, journal, behavior="completed"):
        self.journal = journal
        self.behavior = behavior

    def execute(self, request):
        self.journal.events.append("adapter")

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
            reason="done",
        )


class LockProbe:
    """An adapter that needs the state lock while it runs."""

    requires_grant = False

    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.took_the_lock = False

    def execute(self, request):
        with state_lock(self.data_dir, timeout=1):
            self.took_the_lock = True

        return ExecutionOutcome(
            task_id=request.task_id,
            outcome=EXECUTION_OUTCOME_COMPLETED,
            reason="done",
        )


def _setup(tmp_path, adapter, guard=None, status="ready"):
    """Build a coordinator and one task in isolated registries."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")
    goal = Goal.create(description="Guarded goal", project="TestProject")
    goal_registry.add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Guarded task")
    task_registry.add_task(task)

    if status != "pending":
        task_registry.update_task_status(task.id, status)

    adapters = ExecutionAdapterRegistry()
    adapters.register("test", adapter)
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
        state_guard=guard,
    )

    return coordinator, task


@pytest.mark.parametrize(
    "behavior",
    ["completed", "raises", "invalid", "wrong task"],
)
def test_guard_covers_the_start_and_the_outcome_but_not_the_adapter(
    tmp_path,
    behavior,
) -> None:
    """The guard is held twice, and never while the adapter runs."""
    journal = Journal()
    coordinator, task = _setup(
        tmp_path,
        JournalAdapter(journal, behavior),
        journal.guard,
    )

    coordinator.coordinate(ExecutionRequest(task_id=task.id, target="test"))

    assert journal.events == ["enter", "exit", "adapter", "enter", "exit"]


def test_guard_covers_a_refused_start(tmp_path) -> None:
    """A refused start reads state under the guard and runs no adapter."""
    journal = Journal()
    coordinator, task = _setup(
        tmp_path,
        JournalAdapter(journal),
        journal.guard,
        status="pending",
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="test"),
    )

    assert result.status == "rejected"
    assert journal.events == ["enter", "exit"]


def test_guard_is_not_entered_for_an_unknown_target(tmp_path) -> None:
    """An unknown target is refused before any state is touched."""
    journal = Journal()
    coordinator, task = _setup(
        tmp_path,
        JournalAdapter(journal),
        journal.guard,
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="nowhere"),
    )

    assert result.status == "rejected"
    assert journal.events == []


def test_state_lock_is_free_while_the_adapter_runs(tmp_path) -> None:
    """With the real lock as the guard, the adapter can take the lock."""
    probe = LockProbe(tmp_path)
    coordinator, task = _setup(
        tmp_path,
        probe,
        lambda: state_lock(tmp_path),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="test"),
    )

    assert probe.took_the_lock
    assert result.status == "completed"


_DRIVER = """
import sys

from aic_control_centre.config import load_config
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import ExecutionCoordinator
from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.locking import state_lock


class Instant:
    requires_grant = False

    def execute(self, request):
        return ExecutionOutcome(
            task_id=request.task_id,
            outcome="completed",
            reason="done",
        )


adapters = ExecutionAdapterRegistry()
adapters.register("instant", Instant())
data_dir = load_config().data_dir
coordinator = ExecutionCoordinator(
    adapter_registry=adapters,
    state_guard=lambda: state_lock(data_dir),
)
result = coordinator.coordinate(
    ExecutionRequest(task_id=sys.argv[1], target="instant"),
)
print(result.status)
"""


def test_concurrent_coordinators_lose_no_updates(tmp_path) -> None:
    """Coordinators that share the state lock keep every update.

    Without it, processes that overlap overwrite each other's task and
    record files: several report completed and only one task is.
    """
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")
    goal = Goal.create(description="Concurrent goal", project="TestProject")
    goal_registry.add_goal(goal)
    task_ids = []
    count = 8

    for number in range(count):
        task = Task.create(goal_id=goal.id, title=f"task {number}")
        task_registry.add_task(task)
        task_registry.update_task_status(task.id, "ready")
        task_ids.append(task.id)

    environment = {**os.environ, "AIC_DATA_DIR": str(tmp_path)}
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", _DRIVER, task_id],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for task_id in task_ids
    ]
    outputs = [process.communicate(timeout=120) for process in processes]

    assert [process.returncode for process in processes] == [0] * count, [
        output for output in outputs if output[1]
    ]
    assert [out.strip() for out, _ in outputs] == ["completed"] * count

    statuses = [
        task.status
        for task in TaskRegistry(tmp_path / "tasks.json").list_tasks()
    ]
    records = ExecutionRecordRegistry.beside(
        tmp_path / "tasks.json",
    ).list_records()

    assert statuses == ["completed"] * count
    assert len(records) == count
    assert not any(record.is_open for record in records)
