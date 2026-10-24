"""Tests for the read-only adapter wrapper."""

import shutil
import sys

import pytest

from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import ExecutionCoordinator
from aic_control_centre.execution.outcome import (
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
)
from aic_control_centre.execution.process import ProcessAdapter
from aic_control_centre.execution.readonly import (
    READ_ONLY_REASON,
    ReadOnlyAdapter,
    describe_changes,
)
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.snapshot import Changes
from aic_control_centre.execution.start import ExecutionStarter
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import Project
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


class Acting:
    """An adapter that runs an action on the project and reports it done."""

    requires_grant = False
    description = "acts on the project"

    def __init__(self, action=None, outcome="completed", attempt_id=None):
        self.action = action
        self.outcome = outcome
        self.attempt_id = attempt_id
        self.requests = []

    def execute(self, request):
        self.requests.append(request)

        if self.action is not None:
            self.action(request.project_path)

        return ExecutionOutcome(
            task_id=request.task_id,
            outcome=self.outcome,
            reason="done",
            attempt_id=self.attempt_id,
        )


class Failing:
    """An adapter that raises, after an optional action."""

    requires_grant = False

    def __init__(self, action=None):
        self.action = action

    def execute(self, request):
        if self.action is not None:
            self.action(request.project_path)

        raise RuntimeError("adapter broke")


def _project(tmp_path):
    project = tmp_path / "project"
    (project / "sub").mkdir(parents=True)
    (project / "a.txt").write_bytes(b"alpha")
    (project / "sub" / "b.txt").write_bytes(b"beta")

    return project


def _request(project, task_id="task-1"):
    return ExecutionRequest(
        task_id=task_id,
        target="inspect",
        project_path=project,
    )


def _read_everything(project):
    for path in project.rglob("*"):
        if path.is_file():
            path.read_bytes()


def test_a_run_that_only_reads_is_returned_as_it_was(tmp_path) -> None:
    """Nothing changed, so the outcome of the adapter stands."""
    project = _project(tmp_path)
    inner = Acting(_read_everything)
    request = _request(project)

    outcome = ReadOnlyAdapter(inner).execute(request)

    assert outcome.outcome == "completed"
    assert outcome.reason == "done"
    assert inner.requests == [request]


def test_a_new_file_fails_the_run(tmp_path) -> None:
    """The reason says what the rule is and what happened."""
    project = _project(tmp_path)
    inner = Acting(lambda path: (path / "new.txt").write_bytes(b"x"))

    outcome = ReadOnlyAdapter(inner).execute(_request(project))

    assert outcome.outcome == "failed"
    assert outcome.reason.startswith(READ_ONLY_REASON)
    assert "0 changed, 1 added, 0 removed (new.txt)" in outcome.reason
    assert "the cause may be another program" in outcome.reason


def test_a_changed_file_fails_the_run(tmp_path) -> None:
    """A rewrite of a file is a change."""
    project = _project(tmp_path)
    inner = Acting(lambda path: (path / "a.txt").write_bytes(b"ALPHA"))

    outcome = ReadOnlyAdapter(inner).execute(_request(project))

    assert outcome.outcome == "failed"
    assert "1 changed, 0 added, 0 removed (a.txt)" in outcome.reason


def test_a_removed_file_fails_the_run(tmp_path) -> None:
    """Removing a file in a subdirectory is a change."""
    project = _project(tmp_path)
    inner = Acting(lambda path: (path / "sub" / "b.txt").unlink())

    outcome = ReadOnlyAdapter(inner).execute(_request(project))

    assert outcome.outcome == "failed"
    assert "0 changed, 0 added, 1 removed (sub/b.txt)" in outcome.reason


def test_a_new_empty_directory_fails_the_run(tmp_path) -> None:
    """A directory counts, even when it holds nothing."""
    project = _project(tmp_path)
    inner = Acting(lambda path: (path / "empty").mkdir())

    outcome = ReadOnlyAdapter(inner).execute(_request(project))

    assert outcome.outcome == "failed"
    assert "1 added" in outcome.reason


def test_a_failed_outcome_with_a_change_reports_the_change(tmp_path) -> None:
    """A change is reported even when the adapter said it failed."""
    project = _project(tmp_path)
    inner = Acting(
        lambda path: (path / "x").write_bytes(b"x"),
        outcome="failed",
    )

    outcome = ReadOnlyAdapter(inner).execute(_request(project))

    assert outcome.outcome == "failed"
    assert outcome.reason.startswith(READ_ONLY_REASON)


def test_a_failed_outcome_without_a_change_is_left_alone(tmp_path) -> None:
    """The wrapper adds nothing when nothing changed."""
    project = _project(tmp_path)
    inner = Acting(outcome="failed")

    outcome = ReadOnlyAdapter(inner).execute(_request(project))

    assert outcome.outcome == "failed"
    assert outcome.reason == "done"


def test_the_attempt_of_the_outcome_is_kept(tmp_path) -> None:
    """The coordinator ties an outcome to its attempt, so it must stay."""
    project = _project(tmp_path)
    inner = Acting(
        lambda path: (path / "x").write_bytes(b"x"),
        attempt_id="attempt-9",
    )

    outcome = ReadOnlyAdapter(inner).execute(_request(project))

    assert outcome.attempt_id == "attempt-9"


def test_an_error_in_the_adapter_is_raised_when_nothing_changed(
    tmp_path,
) -> None:
    """The coordinator handles the error, as it does without the wrapper."""
    project = _project(tmp_path)

    with pytest.raises(RuntimeError, match="adapter broke"):
        ReadOnlyAdapter(Failing()).execute(_request(project))


def test_a_change_made_before_an_error_is_reported_instead(tmp_path) -> None:
    """The change is what matters, so the error does not hide it."""
    project = _project(tmp_path)
    inner = Failing(lambda path: (path / "x").write_bytes(b"x"))

    outcome = ReadOnlyAdapter(inner).execute(_request(project))

    assert outcome.outcome == "failed"
    assert outcome.reason.startswith(READ_ONLY_REASON)


def test_a_project_that_cannot_be_read_stops_the_run(tmp_path) -> None:
    """The adapter does not run when nothing can be checked."""
    inner = Acting()

    outcome = ReadOnlyAdapter(inner).execute(_request(tmp_path / "missing"))

    assert outcome.outcome == "failed"
    assert outcome.reason.startswith(
        "the project could not be read before the run: ",
    )
    assert inner.requests == []


def test_a_project_that_vanishes_during_the_run_is_a_failure(tmp_path) -> None:
    """If it cannot be read afterwards, it cannot be called unchanged."""
    project = _project(tmp_path)
    inner = Acting(shutil.rmtree)

    outcome = ReadOnlyAdapter(inner).execute(_request(project))

    assert outcome.outcome == "failed"
    assert outcome.reason.startswith(
        "the project could not be read after the run: ",
    )


def test_a_request_without_a_path_is_not_run(tmp_path) -> None:
    """There is nothing to check, so nothing runs."""
    inner = Acting()

    outcome = ReadOnlyAdapter(inner).execute(
        ExecutionRequest(task_id="task-1", target="inspect"),
    )

    assert outcome.outcome == "failed"
    assert outcome.reason == "the request has no project path"
    assert inner.requests == []


def test_two_snapshots_are_taken_around_one_run(tmp_path) -> None:
    """One before, one after, and none anywhere else."""
    project = _project(tmp_path)
    taken = []

    def take(path):
        taken.append(path)

        return {}

    inner = Acting()

    ReadOnlyAdapter(inner, take=take).execute(_request(project))

    assert taken == [project, project]
    assert len(inner.requests) == 1


def test_the_wrapper_always_needs_a_project() -> None:
    """The coordinator must give it a path, whatever the adapter says."""
    assert ReadOnlyAdapter(Acting()).requires_project is True


def test_the_wrapper_asks_for_a_grant_when_the_adapter_does() -> None:
    """The grant rule of the wrapped adapter is the rule of the wrapper."""
    assert ReadOnlyAdapter(Acting()).requires_grant is False
    assert ReadOnlyAdapter(object()).requires_grant is True


def test_the_wrapper_describes_the_wrapped_adapter() -> None:
    """aic task targets shows the description of the adapter."""
    assert ReadOnlyAdapter(Acting()).description == "acts on the project"
    assert ReadOnlyAdapter(object()).description == ""


def test_the_reason_shows_a_few_names_and_is_always_short() -> None:
    """Counts for everything, names for the first three, and a limit."""
    names = tuple("n%d-%s" % (number, "x" * 200) for number in range(500))

    reason = describe_changes(Changes(added=names))

    assert reason.startswith(READ_ONLY_REASON + ": 0 changed, 500 added")
    assert reason.count("xxx...") == 3
    assert len(reason) < 1000


def test_names_in_the_reason_are_escaped() -> None:
    """A name from the project cannot move the cursor or hide text."""
    reason = describe_changes(Changes(changed=("a\nb\x1b[2J",)))

    assert "(a\\x0ab\\x1b[2J)" in reason
    assert "\n" not in reason
    assert "\x1b" not in reason


WRITER = """
import json, pathlib, sys
request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
if %s:
    (pathlib.Path(request["project_path"]) / "written.txt").write_text("x")
print(json.dumps({"outcome": "completed", "reason": "child done"}))
"""


def _child(writes):
    return ProcessAdapter(
        [sys.executable, "-c", WRITER % writes],
        requires_grant=False,
        requires_project=True,
    )


def test_a_child_process_that_writes_a_file_is_caught(tmp_path) -> None:
    """The check works on code that AIC does not control from outside."""
    project = _project(tmp_path)

    outcome = ReadOnlyAdapter(_child(True)).execute(_request(project))

    assert outcome.outcome == "failed"
    assert "1 added" in outcome.reason
    assert "written.txt" in outcome.reason


def test_a_child_process_that_writes_nothing_completes(tmp_path) -> None:
    """The same child, with no write, is not disturbed."""
    project = _project(tmp_path)

    outcome = ReadOnlyAdapter(_child(False)).execute(_request(project))

    assert outcome.outcome == "completed"
    assert outcome.reason == "child done"


class InMemoryProjects:
    def __init__(self, *projects):
        self.projects = {project.name: project for project in projects}

    def get_project(self, name):
        return self.projects.get(name)


class InMemoryGrants:
    def __init__(self, *granted):
        self.granted = set(granted)

    def is_granted(self, project, target):
        return (project, target) in self.granted


def _coordinator(tmp_path, adapter, project, grants=None):
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")
    goal = Goal.create(description="Project goal", project="alpha")
    goal_registry.add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Project task")
    task_registry.add_task(task)
    task_registry.update_task_status(task.id, "ready")
    evaluator = TaskReadinessEvaluator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    )
    adapters = ExecutionAdapterRegistry()
    adapters.register("inspect", adapter)
    coordinator = ExecutionCoordinator(
        adapter_registry=adapters,
        starter=ExecutionStarter(
            admission=ExecutionAdmission(
                evaluator,
                grants,
                InMemoryProjects(Project(name="alpha", path=project)),
            ),
            task_registry=task_registry,
        ),
        outcome_recorder=ExecutionOutcomeRecorder(
            task_registry=task_registry,
            goal_registry=goal_registry,
        ),
    )

    return coordinator, task_registry, task


def test_through_the_coordinator_a_clean_run_completes_the_task(
    tmp_path,
) -> None:
    """The wrapper gets the registered path and the task completes."""
    project = _project(tmp_path)
    inner = Acting(_read_everything)
    coordinator, task_registry, task = _coordinator(
        tmp_path,
        ReadOnlyAdapter(inner),
        project,
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="inspect"),
    )

    assert result.status == "completed"
    assert task_registry.get_task(task.id).status == "completed"
    assert inner.requests[0].project_path == project


def test_through_the_coordinator_a_change_fails_the_task(tmp_path) -> None:
    """The failure is recorded like any other, with the reason."""
    project = _project(tmp_path)
    inner = Acting(lambda path: (path / "x").write_bytes(b"x"))
    coordinator, task_registry, task = _coordinator(
        tmp_path,
        ReadOnlyAdapter(inner),
        project,
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="inspect"),
    )

    assert result.status == "failed"
    assert result.reason.startswith(READ_ONLY_REASON)
    assert task_registry.get_task(task.id).status == "failed"


def test_through_the_coordinator_a_missing_directory_is_refused(
    tmp_path,
) -> None:
    """Admission refuses before the wrapper or the adapter runs."""
    inner = Acting()
    coordinator, task_registry, task = _coordinator(
        tmp_path,
        ReadOnlyAdapter(inner),
        tmp_path / "gone",
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="inspect"),
    )

    assert result.status == "rejected"
    assert "does not exist" in result.reason
    assert inner.requests == []
    assert task_registry.get_task(task.id).status == "ready"


def test_through_the_coordinator_the_grant_rule_still_applies(
    tmp_path,
) -> None:
    """An adapter that says nothing about grants needs one, wrapped or not."""
    project = _project(tmp_path)

    class Silent:
        def execute(self, request):
            raise AssertionError("must not run")

    coordinator, _, task = _coordinator(
        tmp_path,
        ReadOnlyAdapter(Silent()),
        project,
        grants=InMemoryGrants(),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="inspect"),
    )

    assert result.status == "rejected"
    assert "not granted" in result.reason
