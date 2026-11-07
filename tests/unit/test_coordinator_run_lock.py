"""Tests for the run lock that the coordinator holds while a run lasts."""

import os
from contextlib import contextmanager
from dataclasses import replace

import pytest

from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import (
    EXECUTION_COORDINATION_COMPLETED,
    EXECUTION_COORDINATION_FAILED,
    EXECUTION_COORDINATION_REJECTED,
    NO_OWNER_NOTE,
    ExecutionCoordinateResult,
    ExecutionCoordinator,
)
from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_COMPLETED,
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
)
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.run_lock import (
    OWNER_ALIVE,
    OWNER_UNKNOWN,
    RUNS_DIR_NAME,
    RunLockError,
    hold_run_lock,
    probe_run_lock,
)
from aic_control_centre.execution.start import ExecutionStarter
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.locking import StateLockError
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.tasks.model import TASK_STATUS_READY, Task
from aic_control_centre.tasks.registry import TaskRegistry


class Probe:
    """An adapter that looks at the run lock while it runs."""

    requires_grant = False

    def __init__(self, data_dir, events, behavior="completed"):
        self.data_dir = data_dir
        self.events = events
        self.behavior = behavior
        self.ran = False
        self.seen = None
        self.attempt_id = None
        self.listing = None

    def execute(self, request):
        records = ExecutionRecordRegistry.beside(
            self.data_dir / "tasks.json",
        )
        attempt = records.get_open_attempt(request.task_id)

        self.ran = True
        self.events.append("adapter")
        self.attempt_id = attempt.id
        self.seen = probe_run_lock(self.data_dir, attempt.id)
        self.listing = os.listdir(self.data_dir / RUNS_DIR_NAME)

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
            reason="probe completed",
        )


def build(tmp_path, adapter_behavior="completed", **guards):
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(description="Run lock goal", project="TestProject")
    goal_registry.add_goal(goal)

    task = Task.create(goal_id=goal.id, title="Run lock task")
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, TASK_STATUS_READY)

    events = []
    adapter = Probe(tmp_path, events, adapter_behavior)
    registry = ExecutionAdapterRegistry()
    registry.register("test", adapter)

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
        **guards,
    )

    return coordinator, task, adapter, events


def real_run_guard(data_dir):
    def guard(attempt_id):
        return hold_run_lock(data_dir, attempt_id)

    return guard


def request_for(task):
    return ExecutionRequest(task_id=task.id, target="test")


def test_the_lock_is_held_while_the_adapter_runs(tmp_path) -> None:
    coordinator, task, adapter, _ = build(
        tmp_path,
        run_guard=real_run_guard(tmp_path),
    )

    result = coordinator.coordinate(request_for(task))

    attempts = ExecutionRecordRegistry.beside(
        tmp_path / "tasks.json",
    ).list_attempts(task.id)

    assert result.status == EXECUTION_COORDINATION_COMPLETED
    assert adapter.seen == OWNER_ALIVE
    assert adapter.listing == [attempts[0].id + ".lock"]
    assert adapter.attempt_id == attempts[0].id


def test_the_lock_is_released_and_its_file_removed_at_the_end(
    tmp_path,
) -> None:
    coordinator, task, adapter, _ = build(
        tmp_path,
        run_guard=real_run_guard(tmp_path),
    )

    coordinator.coordinate(request_for(task))

    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []
    assert probe_run_lock(tmp_path, adapter.attempt_id) == OWNER_UNKNOWN


@pytest.mark.parametrize(
    "behavior",
    ["raises", "invalid", "wrong task"],
)
def test_the_lock_is_released_when_the_adapter_misbehaves(
    tmp_path,
    behavior,
) -> None:
    coordinator, task, adapter, _ = build(
        tmp_path,
        adapter_behavior=behavior,
        run_guard=real_run_guard(tmp_path),
    )

    result = coordinator.coordinate(request_for(task))

    assert result.status == EXECUTION_COORDINATION_FAILED
    assert adapter.seen == OWNER_ALIVE
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []


def test_the_order_of_the_guards_around_a_run(tmp_path) -> None:
    events = []

    @contextmanager
    def state_guard():
        events.append("state enter")

        try:
            yield
        finally:
            events.append("state exit")

    @contextmanager
    def run_guard(attempt_id):
        events.append("run enter")

        try:
            yield
        finally:
            events.append("run exit")

    coordinator, task, adapter, adapter_events = build(
        tmp_path,
        state_guard=state_guard,
        run_guard=run_guard,
    )
    adapter.events = events
    adapter.data_dir = tmp_path
    (tmp_path / RUNS_DIR_NAME).mkdir()

    coordinator.coordinate(request_for(task))

    assert events == [
        "state enter",
        "state exit",
        "run enter",
        "adapter",
        "state enter",
        "state exit",
        "run exit",
    ]


def test_the_lock_is_still_held_when_the_outcome_is_recorded(
    tmp_path,
) -> None:
    seen = []
    entries = []
    records = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")

    @contextmanager
    def state_guard():
        entries.append(1)

        if len(entries) == 1:
            seen.append(os.path.lexists(tmp_path / RUNS_DIR_NAME))
        else:
            attempt = records.get_open_attempt(task.id)
            seen.append(probe_run_lock(tmp_path, attempt.id))

        yield

    coordinator, task, adapter, _ = build(
        tmp_path,
        state_guard=state_guard,
        run_guard=real_run_guard(tmp_path),
    )

    coordinator.coordinate(request_for(task))

    assert seen == [False, OWNER_ALIVE]


def test_the_attempt_is_closed_before_the_lock_is_released(
    tmp_path,
) -> None:
    records = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")
    open_at_release = []

    @contextmanager
    def run_guard(attempt_id):
        yield
        open_at_release.append(records.get_open_attempt(task.id))

    coordinator, task, adapter, _ = build(tmp_path, run_guard=run_guard)
    (tmp_path / RUNS_DIR_NAME).mkdir()

    coordinator.coordinate(request_for(task))

    assert open_at_release == [None]


def test_the_guard_is_given_the_id_of_the_opened_attempt(tmp_path) -> None:
    given = []

    @contextmanager
    def run_guard(attempt_id):
        given.append(attempt_id)
        yield

    coordinator, task, adapter, _ = build(tmp_path, run_guard=run_guard)
    (tmp_path / RUNS_DIR_NAME).mkdir()

    coordinator.coordinate(request_for(task))

    attempts = ExecutionRecordRegistry.beside(
        tmp_path / "tasks.json",
    ).list_attempts(task.id)

    assert given == [attempts[0].id]


def test_the_lock_is_released_when_the_outcome_cannot_be_recorded(
    tmp_path,
) -> None:
    entries = []

    @contextmanager
    def state_guard():
        entries.append(1)

        if len(entries) == 2:
            raise StateLockError("another aic process is using the files")

        yield

    coordinator, task, adapter, _ = build(
        tmp_path,
        state_guard=state_guard,
        run_guard=real_run_guard(tmp_path),
    )

    with pytest.raises(StateLockError):
        coordinator.coordinate(request_for(task))

    records = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")

    assert adapter.seen == OWNER_ALIVE
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []
    assert records.get_open_attempt(task.id) is not None


def test_a_run_goes_on_when_the_lock_cannot_be_taken(tmp_path) -> None:
    @contextmanager
    def run_guard(attempt_id):
        raise RunLockError("the disk is full")
        yield

    coordinator, task, adapter, _ = build(tmp_path, run_guard=run_guard)
    (tmp_path / RUNS_DIR_NAME).mkdir()

    result = coordinator.coordinate(request_for(task))

    attempts = ExecutionRecordRegistry.beside(
        tmp_path / "tasks.json",
    ).list_attempts(task.id)

    assert adapter.ran is True
    assert result.status == EXECUTION_COORDINATION_COMPLETED
    assert result.reason == "probe completed"
    assert result.note == f"{NO_OWNER_NOTE} (the disk is full)"
    assert attempts[0].reason == "probe completed"
    assert attempts[0].ended_as == "completed"


def test_the_note_is_one_line(tmp_path) -> None:
    @contextmanager
    def run_guard(attempt_id):
        raise RunLockError("first line\n   second line\n")
        yield

    coordinator, task, adapter, _ = build(tmp_path, run_guard=run_guard)
    (tmp_path / RUNS_DIR_NAME).mkdir()

    result = coordinator.coordinate(request_for(task))

    assert "\n" not in result.note
    assert result.note.endswith("(first line second line)")


def test_without_a_run_guard_nothing_is_locked_and_there_is_no_note(
    tmp_path,
) -> None:
    coordinator, task, adapter, _ = build(tmp_path)
    (tmp_path / RUNS_DIR_NAME).mkdir()

    result = coordinator.coordinate(request_for(task))

    assert adapter.ran is True
    assert result.note is None
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []


def test_a_normal_run_has_no_note(tmp_path) -> None:
    coordinator, task, adapter, _ = build(
        tmp_path,
        run_guard=real_run_guard(tmp_path),
    )

    result = coordinator.coordinate(request_for(task))

    assert result.note is None


def test_a_start_without_an_attempt_id_takes_no_lock(tmp_path) -> None:
    calls = []

    @contextmanager
    def run_guard(attempt_id):
        calls.append(attempt_id)
        yield

    coordinator, task, adapter, _ = build(tmp_path, run_guard=run_guard)
    real_start = coordinator.starter.start

    def start_without_an_id(request):
        return replace(real_start(request), attempt_id=None)

    coordinator.starter.start = start_without_an_id

    result = coordinator.coordinate(request_for(task))

    assert adapter.ran is True
    assert calls == []
    assert result.note is None


def test_a_rejected_start_takes_no_lock(tmp_path) -> None:
    calls = []

    @contextmanager
    def run_guard(attempt_id):
        calls.append(attempt_id)
        yield

    coordinator, task, adapter, _ = build(tmp_path, run_guard=run_guard)

    result = coordinator.coordinate(
        ExecutionRequest(task_id="no-such-task", target="test"),
    )

    assert result.status == EXECUTION_COORDINATION_REJECTED
    assert calls == []
    assert adapter.ran is False


def test_an_unknown_target_takes_no_lock(tmp_path) -> None:
    calls = []

    @contextmanager
    def run_guard(attempt_id):
        calls.append(attempt_id)
        yield

    coordinator, task, adapter, _ = build(tmp_path, run_guard=run_guard)

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="no-such-target"),
    )

    assert result.status == EXECUTION_COORDINATION_REJECTED
    assert calls == []


def test_a_note_cannot_be_blank() -> None:
    with pytest.raises(ValueError, match="note cannot be empty"):
        ExecutionCoordinateResult(
            task_id="t",
            status=EXECUTION_COORDINATION_COMPLETED,
            outcome="completed",
            reason="done",
            note="  ",
        )

    result = ExecutionCoordinateResult(
        task_id="t",
        status=EXECUTION_COORDINATION_COMPLETED,
        outcome="completed",
        reason="done",
    )

    assert result.note is None
