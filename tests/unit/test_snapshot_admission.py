"""Tests for the snapshot limit in admission, start and the coordinator."""

import pytest

from aic_control_centre.execution import snapshot as snapshot_module
from aic_control_centre.execution.admission import ExecutionAdmission
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import ExecutionCoordinator
from aic_control_centre.execution.outcome import (
    ExecutionOutcome,
    ExecutionOutcomeRecorder,
)
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.start import ExecutionStarter
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import Project
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry

TOO_MUCH = (
    "which is too much to check before and after a read-only run; "
    "the files were counted until the limit was passed"
)
ADVICE = "register a directory with fewer files as the project"


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


class QuietAdapter:
    """An adapter that needs a project and says nothing about snapshots."""

    requires_grant = False
    requires_project = True

    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)

        return ExecutionOutcome(
            task_id=request.task_id,
            outcome="completed",
            reason="done",
        )


class RecordingAdapter(QuietAdapter):
    """An adapter that says that it takes snapshots."""

    snapshots = True


def _files(directory, count, size=1):
    directory.mkdir(parents=True, exist_ok=True)

    for number in range(count):
        (directory / f"f{number}.txt").write_bytes(b"x" * size)

    return directory


def _make_task(tmp_path, status="ready"):
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")
    goal = Goal.create(description="Project goal", project="alpha")
    goal_registry.add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Project task")
    task_registry.add_task(task)

    if status != "pending":
        task_registry.update_task_status(task.id, status)

    evaluator = TaskReadinessEvaluator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    )

    return evaluator, goal_registry, task_registry, task


def _request(task, **options):
    options.setdefault("requires_grant", False)
    options.setdefault("requires_project", True)
    options.setdefault("snapshots", True)

    return ExecutionRequest(task_id=task.id, target="inspect", **options)


def _admission(tmp_path, directory, grants=None, status="ready"):
    evaluator, goals, tasks, task = _make_task(tmp_path, status)
    admission = ExecutionAdmission(
        evaluator,
        grants=grants,
        projects=InMemoryProjects(Project(name="alpha", path=directory)),
    )

    return admission, task, goals, tasks


@pytest.fixture
def survey_calls(monkeypatch):
    """Keep the calls of the survey, which still does its work."""
    calls = []
    real = snapshot_module.survey_project

    def survey_project(*arguments, **options):
        calls.append(arguments)

        return real(*arguments, **options)

    monkeypatch.setattr(snapshot_module, "survey_project", survey_project)

    return calls


def test_a_request_does_not_take_snapshots_by_default(tmp_path) -> None:
    """A request that is built by hand is not surveyed."""
    task = _make_task(tmp_path)[3]

    request = ExecutionRequest(task_id=task.id, target="inspect")

    assert request.snapshots is False


def test_too_many_files_are_refused_with_the_reason(
    tmp_path,
    monkeypatch,
) -> None:
    """The reason says what was passed, and what to do about it."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 2)
    admission, task, _, _ = _admission(tmp_path, _files(tmp_path / "p", 3))

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert result.reason == (
        f"project alpha has more than 2 files, {TOO_MUCH}; {ADVICE}"
    )


def test_the_folders_with_the_files_are_named(
    tmp_path,
    monkeypatch,
) -> None:
    """The reason names the folder that holds the files counted so far."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 2)
    project = tmp_path / "p"
    _files(project / "site-packages", 3)
    admission, task, _, _ = _admission(tmp_path, project)

    result = admission.evaluate(_request(task))

    assert result.reason == (
        f"project alpha has more than 2 files, {TOO_MUCH}; "
        f"the folders with the most files so far: site-packages (3); "
        f"{ADVICE}"
    )


def test_a_count_of_a_thousand_or_more_has_a_separator(
    tmp_path,
    monkeypatch,
) -> None:
    """Large counts are told as people write them."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 999)
    project = tmp_path / "p"
    _files(project / "pkg", 1000)
    admission, task, _, _ = _admission(tmp_path, project)

    result = admission.evaluate(_request(task))

    assert "has more than 999 files" in result.reason
    assert "the folders with the most files so far: pkg (1,000);" in (
        result.reason
    )


def test_the_names_of_folders_are_escaped_in_the_reason(
    tmp_path,
    monkeypatch,
) -> None:
    """A folder name is not printed as it is when it has a control code.

    This checks nothing where such a name cannot be made, which is the
    case on Windows.
    """
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 2)
    project = tmp_path / "p"
    name = "bad\nname"

    try:
        _files(project / name, 3)
    except OSError:
        return

    admission, task, _, _ = _admission(tmp_path, project)

    result = admission.evaluate(_request(task))

    assert "\n" not in result.reason
    assert snapshot_module.escape_name(name) in result.reason


def test_too_many_bytes_are_refused_with_the_reason(
    tmp_path,
    monkeypatch,
) -> None:
    """The size limit is told as a size."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_BYTES", 5)
    admission, task, _, _ = _admission(
        tmp_path, _files(tmp_path / "p", 2, size=4),
    )

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert result.reason == (
        f"project alpha has more than 5 bytes in files, {TOO_MUCH}; {ADVICE}"
    )


def test_exactly_at_the_limits_is_accepted(tmp_path, monkeypatch) -> None:
    """Three files of two bytes are allowed by limits of 3 and 6."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 3)
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_BYTES", 6)
    directory = _files(tmp_path / "p", 3, size=2)
    admission, task, _, _ = _admission(tmp_path, directory)

    result = admission.evaluate(_request(task))

    assert result.accepted is True
    assert result.project_path == directory


def test_a_request_that_takes_no_snapshot_is_not_surveyed(
    tmp_path,
    monkeypatch,
    survey_calls,
) -> None:
    """The same project is accepted when the adapter takes no snapshot."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 1)
    admission, task, _, _ = _admission(tmp_path, _files(tmp_path / "p", 3))

    result = admission.evaluate(_request(task, snapshots=False))

    assert result.accepted is True
    assert survey_calls == []


def test_a_request_with_no_project_is_not_surveyed(
    tmp_path,
    survey_calls,
) -> None:
    """There is no directory to survey when the target needs no project."""
    admission, task, _, _ = _admission(tmp_path, _files(tmp_path / "p", 3))

    result = admission.evaluate(_request(task, requires_project=False))

    assert result.accepted is True
    assert survey_calls == []


def test_the_survey_is_given_the_registered_path_and_the_limits(
    tmp_path,
    survey_calls,
) -> None:
    """It is run on the registered directory with the limits of the module."""
    directory = _files(tmp_path / "p", 2)
    admission, task, _, _ = _admission(tmp_path, directory)

    admission.evaluate(_request(task))

    assert survey_calls == [
        (
            directory,
            snapshot_module.SNAPSHOT_MAX_FILES,
            snapshot_module.SNAPSHOT_MAX_BYTES,
        ),
    ]


def test_a_missing_directory_is_refused_before_the_survey(
    tmp_path,
    survey_calls,
) -> None:
    """The cheap check comes first, and its reason is unchanged."""
    admission, task, _, _ = _admission(tmp_path, tmp_path / "gone")

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert "does not exist" in result.reason
    assert survey_calls == []


def test_a_missing_grant_is_refused_before_the_survey(
    tmp_path,
    monkeypatch,
    survey_calls,
) -> None:
    """A project with no grant is not walked."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 1)
    admission, task, _, _ = _admission(
        tmp_path, _files(tmp_path / "p", 3), grants=InMemoryGrants(),
    )

    result = admission.evaluate(_request(task, requires_grant=True))

    assert result.reason == "target inspect is not granted for project alpha"
    assert survey_calls == []


def test_a_task_that_is_not_ready_is_refused_before_the_survey(
    tmp_path,
    survey_calls,
) -> None:
    """Readiness is still the first check."""
    admission, task, _, _ = _admission(
        tmp_path, _files(tmp_path / "p", 3), status="pending",
    )

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert survey_calls == []


def test_a_directory_that_cannot_be_surveyed_is_refused(
    tmp_path,
    monkeypatch,
) -> None:
    """If the directory cannot be read now, the reason says so."""
    directory = _files(tmp_path / "p", 1)
    admission, task, _, _ = _admission(tmp_path, directory)

    def survey_project(*arguments, **options):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(snapshot_module, "survey_project", survey_project)

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert result.reason == (
        f"the directory of project alpha cannot be read: {directory}; "
        f"Access is denied"
    )


def test_a_refusal_at_start_writes_nothing(tmp_path, monkeypatch) -> None:
    """The task stays ready and no record is made."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 2)
    admission, task, _, tasks = _admission(tmp_path, _files(tmp_path / "p", 3))

    result = ExecutionStarter(
        admission=admission,
        task_registry=tasks,
    ).start(_request(task))

    assert result.started is False
    assert "has more than 2 files" in result.reason
    assert tasks.get_task(task.id).status == "ready"
    assert not (tmp_path / "executions.json").exists()


def _coordinator(tmp_path, adapter, directory):
    evaluator, goals, tasks, task = _make_task(tmp_path)
    adapters = ExecutionAdapterRegistry()
    adapters.register("inspect", adapter)
    coordinator = ExecutionCoordinator(
        adapter_registry=adapters,
        starter=ExecutionStarter(
            admission=ExecutionAdmission(
                evaluator,
                projects=InMemoryProjects(
                    Project(name="alpha", path=directory),
                ),
            ),
            task_registry=tasks,
        ),
        outcome_recorder=ExecutionOutcomeRecorder(
            task_registry=tasks,
            goal_registry=goals,
        ),
    )

    return coordinator, tasks, goals, task


def test_the_coordinator_asks_the_adapter_whether_it_takes_snapshots(
    tmp_path,
    monkeypatch,
) -> None:
    """An adapter that says so is refused for a project that is too large."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 2)
    adapter = RecordingAdapter()
    coordinator, tasks, goals, task = _coordinator(
        tmp_path, adapter, _files(tmp_path / "p", 3),
    )
    goal_before = goals.get_goal(task.goal_id).status

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="inspect"),
    )

    assert result.status == "rejected"
    assert "has more than 2 files" in result.reason
    assert adapter.requests == []
    assert tasks.get_task(task.id).status == "ready"
    assert goals.get_goal(task.goal_id).status == goal_before
    assert not (tmp_path / "executions.json").exists()


def test_an_adapter_that_does_not_say_so_is_not_surveyed(
    tmp_path,
    monkeypatch,
) -> None:
    """The default is that no snapshot is taken."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 2)
    adapter = QuietAdapter()
    coordinator, tasks, _, task = _coordinator(
        tmp_path, adapter, _files(tmp_path / "p", 3),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="inspect"),
    )

    assert result.status == "completed"
    assert tasks.get_task(task.id).status == "completed"


def test_a_project_within_the_limits_is_run_through_the_coordinator(
    tmp_path,
    monkeypatch,
) -> None:
    """The adapter gets the request, and the task is completed."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 3)
    adapter = RecordingAdapter()
    coordinator, tasks, _, task = _coordinator(
        tmp_path, adapter, _files(tmp_path / "p", 3),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="inspect"),
    )

    assert result.status == "completed"
    assert len(adapter.requests) == 1
    assert tasks.get_task(task.id).status == "completed"
