"""Tests for the project check in admission, start and the coordinator."""

from aic_control_centre.execution.adapters import NoopAdapter
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


class InMemoryProjects:
    """A project source that holds its projects in memory and keeps a log."""

    def __init__(self, *projects):
        self.projects = {project.name: project for project in projects}
        self.asked = []

    def get_project(self, name):
        self.asked.append(name)

        return self.projects.get(name)


class InMemoryGrants:
    def __init__(self, *granted):
        self.granted = set(granted)

    def is_granted(self, project, target):
        return (project, target) in self.granted


class RecordingAdapter:
    """An adapter that needs a project and keeps the requests it is given."""

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


class PlainProjectAdapter(RecordingAdapter):
    """An adapter that says nothing about projects, so it needs none."""

    requires_project = False


class UnreadablePath:
    """A path whose directory cannot be looked at."""

    def __str__(self):
        return "/unreadable"

    def exists(self):
        raise PermissionError("denied")

    def is_dir(self):
        raise PermissionError("denied")


def _directory(tmp_path, name="alpha"):
    path = tmp_path / name
    path.mkdir()

    return path


def _make_task(tmp_path, project="alpha", status="ready"):
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")
    goal = Goal.create(description="Project goal", project=project)
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


def _request(task, target="inspect", **options):
    options.setdefault("requires_grant", False)
    options.setdefault("requires_project", True)

    return ExecutionRequest(task_id=task.id, target=target, **options)


def test_a_registered_directory_is_accepted_and_its_path_returned(
    tmp_path,
) -> None:
    """Admission hands back the path that the registry holds."""
    evaluator, _, _, task = _make_task(tmp_path)
    path = _directory(tmp_path)
    projects = InMemoryProjects(Project(name="alpha", path=path))
    admission = ExecutionAdmission(evaluator, projects=projects)

    result = admission.evaluate(_request(task))

    assert result.accepted is True
    assert result.project_path == path


def test_a_request_that_needs_no_project_is_not_looked_up(tmp_path) -> None:
    """Targets such as noop are not affected, and no path is returned."""
    evaluator, _, _, task = _make_task(tmp_path)
    projects = InMemoryProjects()
    admission = ExecutionAdmission(evaluator, projects=projects)

    result = admission.evaluate(_request(task, requires_project=False))

    assert result.accepted is True
    assert result.project_path is None
    assert projects.asked == []


def test_a_project_that_is_not_registered_is_refused(tmp_path) -> None:
    """The reason names the project."""
    evaluator, _, _, task = _make_task(tmp_path)
    admission = ExecutionAdmission(evaluator, projects=InMemoryProjects())

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert result.reason == "project alpha is not registered"
    assert result.project_path is None


def test_a_directory_that_is_gone_is_refused(tmp_path) -> None:
    """A registered project whose directory was deleted does not run."""
    evaluator, _, _, task = _make_task(tmp_path)
    path = tmp_path / "alpha"
    projects = InMemoryProjects(Project(name="alpha", path=path))
    admission = ExecutionAdmission(evaluator, projects=projects)

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert result.reason == (
        f"the directory of project alpha does not exist: {path}"
    )


def test_a_path_that_is_a_file_is_refused(tmp_path) -> None:
    """A file is not a project directory."""
    evaluator, _, _, task = _make_task(tmp_path)
    path = tmp_path / "alpha"
    path.write_text("not a directory", encoding="utf-8")
    projects = InMemoryProjects(Project(name="alpha", path=path))
    admission = ExecutionAdmission(evaluator, projects=projects)

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert result.reason == (
        f"the path of project alpha is not a directory: {path}"
    )


def test_a_directory_that_cannot_be_read_is_refused(tmp_path) -> None:
    """An error from the file system is a refusal, not a crash."""
    evaluator, _, _, task = _make_task(tmp_path)
    projects = InMemoryProjects(Project(name="alpha", path=UnreadablePath()))
    admission = ExecutionAdmission(evaluator, projects=projects)

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert result.reason == (
        "the directory of project alpha cannot be read: /unreadable"
    )


def test_the_directory_is_checked_at_every_request(tmp_path) -> None:
    """A directory removed after one request is noticed at the next."""
    evaluator, _, _, task = _make_task(tmp_path)
    path = _directory(tmp_path)
    projects = InMemoryProjects(Project(name="alpha", path=path))
    admission = ExecutionAdmission(evaluator, projects=projects)

    assert admission.evaluate(_request(task)).accepted is True

    path.rmdir()

    assert admission.evaluate(_request(task)).accepted is False


def test_admission_with_no_project_source_refuses_by_default(
    tmp_path,
) -> None:
    """Nothing is found unless a source is given."""
    evaluator, _, _, task = _make_task(tmp_path)

    result = ExecutionAdmission(evaluator).evaluate(_request(task))

    assert result.accepted is False
    assert result.reason == "project alpha is not registered"


def test_readiness_is_checked_before_the_project(tmp_path) -> None:
    """A task that is not ready is refused for that reason."""
    evaluator, _, _, task = _make_task(tmp_path, status="pending")
    admission = ExecutionAdmission(evaluator, projects=InMemoryProjects())

    result = admission.evaluate(_request(task))

    assert result.accepted is False
    assert "not registered" not in result.reason


def test_the_project_is_checked_before_the_grant(tmp_path) -> None:
    """A vanished directory is reported as that, not as a missing grant."""
    evaluator, _, _, task = _make_task(tmp_path)
    admission = ExecutionAdmission(
        evaluator,
        InMemoryGrants(),
        InMemoryProjects(),
    )

    result = admission.evaluate(_request(task, requires_grant=True))

    assert result.reason == "project alpha is not registered"


def test_a_usable_directory_still_needs_its_grant(tmp_path) -> None:
    """The project check does not replace the grant check."""
    evaluator, _, _, task = _make_task(tmp_path)
    path = _directory(tmp_path)
    projects = InMemoryProjects(Project(name="alpha", path=path))
    request = _request(task, requires_grant=True)

    refused = ExecutionAdmission(
        evaluator,
        InMemoryGrants(),
        projects,
    ).evaluate(request)
    allowed = ExecutionAdmission(
        evaluator,
        InMemoryGrants(("alpha", "inspect")),
        projects,
    ).evaluate(request)

    assert refused.accepted is False
    assert "not granted" in refused.reason
    assert allowed.accepted is True
    assert allowed.project_path == path


def test_a_start_carries_the_path_and_a_refusal_writes_nothing(
    tmp_path,
) -> None:
    """A refused start opens no attempt and moves no task."""
    evaluator, _, task_registry, task = _make_task(tmp_path)
    path = _directory(tmp_path)
    projects = InMemoryProjects(Project(name="alpha", path=path))

    def starter():
        return ExecutionStarter(
            admission=ExecutionAdmission(evaluator, projects=projects),
            task_registry=task_registry,
        )

    path.rmdir()
    refused = starter().start(_request(task))

    assert refused.started is False
    assert refused.project_path is None
    assert not (tmp_path / "executions.json").exists()
    assert task_registry.get_task(task.id).status == "ready"

    path.mkdir()
    started = starter().start(_request(task))

    assert started.started is True
    assert started.project_path == path
    assert task_registry.get_task(task.id).status == "running"


def _coordinator(tmp_path, adapter, projects):
    evaluator, goal_registry, task_registry, task = _make_task(tmp_path)
    adapters = ExecutionAdapterRegistry()
    adapters.register("inspect", adapter)
    coordinator = ExecutionCoordinator(
        adapter_registry=adapters,
        starter=ExecutionStarter(
            admission=ExecutionAdmission(evaluator, projects=projects),
            task_registry=task_registry,
        ),
        outcome_recorder=ExecutionOutcomeRecorder(
            task_registry=task_registry,
            goal_registry=goal_registry,
        ),
    )

    return coordinator, task_registry, task


def test_the_adapter_is_given_the_registered_path(tmp_path) -> None:
    """The adapter sees the path from the registry, in its request."""
    path = _directory(tmp_path)
    adapter = RecordingAdapter()
    coordinator, _, task = _coordinator(
        tmp_path,
        adapter,
        InMemoryProjects(Project(name="alpha", path=path)),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="inspect"),
    )

    assert result.status == "completed"
    assert [request.project_path for request in adapter.requests] == [path]


def test_a_path_set_by_the_caller_is_not_used(tmp_path) -> None:
    """The registry decides which directory an adapter gets."""
    path = _directory(tmp_path)
    other = _directory(tmp_path, "other")
    adapter = RecordingAdapter()
    coordinator, _, task = _coordinator(
        tmp_path,
        adapter,
        InMemoryProjects(Project(name="alpha", path=path)),
    )

    coordinator.coordinate(
        ExecutionRequest(
            task_id=task.id,
            target="inspect",
            project_path=other,
        ),
    )

    assert [request.project_path for request in adapter.requests] == [path]


def test_a_path_set_by_the_caller_is_not_passed_to_another_adapter(
    tmp_path,
) -> None:
    """An adapter that needs no project never receives a path."""
    path = _directory(tmp_path)
    adapter = PlainProjectAdapter()
    coordinator, _, task = _coordinator(
        tmp_path,
        adapter,
        InMemoryProjects(Project(name="alpha", path=path)),
    )

    coordinator.coordinate(
        ExecutionRequest(
            task_id=task.id,
            target="inspect",
            project_path=path,
        ),
    )

    assert [request.project_path for request in adapter.requests] == [None]


def test_the_adapter_decides_whether_a_project_is_needed(tmp_path) -> None:
    """A caller cannot switch the check off for an adapter that needs it."""
    adapter = RecordingAdapter()
    coordinator, _, task = _coordinator(
        tmp_path,
        adapter,
        InMemoryProjects(),
    )

    result = coordinator.coordinate(
        ExecutionRequest(
            task_id=task.id,
            target="inspect",
            requires_project=False,
        ),
    )

    assert result.status == "rejected"
    assert result.reason == "project alpha is not registered"
    assert adapter.requests == []


def test_a_refused_project_runs_nothing_and_writes_nothing(tmp_path) -> None:
    """The adapter does not run, the task stays ready, no record exists."""
    adapter = RecordingAdapter()
    coordinator, task_registry, task = _coordinator(
        tmp_path,
        adapter,
        InMemoryProjects(Project(name="alpha", path=tmp_path / "gone")),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="inspect"),
    )

    assert result.status == "rejected"
    assert "does not exist" in result.reason
    assert adapter.requests == []
    assert task_registry.get_task(task.id).status == "ready"
    assert not (tmp_path / "executions.json").exists()


def test_noop_is_not_affected_by_a_missing_project(tmp_path) -> None:
    """The noop adapter needs no project, so it still completes the task."""
    coordinator, task_registry, task = _coordinator(
        tmp_path,
        NoopAdapter(),
        InMemoryProjects(),
    )

    result = coordinator.coordinate(
        ExecutionRequest(task_id=task.id, target="inspect"),
    )

    assert result.status == "completed"
    assert task_registry.get_task(task.id).status == "completed"
