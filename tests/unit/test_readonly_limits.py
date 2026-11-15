"""Tests for the limits of the snapshots of the read-only wrapper."""

from aic_control_centre.execution import snapshot as snapshot_module
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.readonly import ReadOnlyAdapter


class Inner:
    """An adapter that does what it is told with the project."""

    requires_grant = False

    def __init__(self, action=None, attempt_id=None):
        self.action = action
        self.attempt_id = attempt_id
        self.runs = 0

    def execute(self, request):
        self.runs += 1

        if self.action is not None:
            self.action(request.project_path)

        return ExecutionOutcome(
            task_id=request.task_id,
            outcome="completed",
            reason="done",
            attempt_id=self.attempt_id,
        )


def _project(tmp_path, files):
    project = tmp_path / "project"
    project.mkdir()

    for number in range(files):
        (project / f"f{number}.txt").write_bytes(b"x")

    return project


def _request(project):
    return ExecutionRequest(
        task_id="task-1",
        target="inspect",
        requires_grant=False,
        requires_project=True,
        project_path=project,
    )


def test_a_project_within_the_limits_runs_as_before(
    tmp_path,
    monkeypatch,
) -> None:
    """Exactly at the limit is a project that is run."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 3)
    inner = Inner()

    outcome = ReadOnlyAdapter(inner).execute(
        _request(_project(tmp_path, 3)),
    )

    assert outcome.outcome == "completed"
    assert inner.runs == 1


def test_a_project_over_the_limit_is_not_run(
    tmp_path,
    monkeypatch,
) -> None:
    """A project that grew since admission fails before the adapter runs."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 2)
    inner = Inner()

    outcome = ReadOnlyAdapter(inner).execute(
        _request(_project(tmp_path, 3)),
    )

    assert outcome.outcome == "failed"
    assert outcome.reason == (
        "the project is too large to check, so nothing was run: "
        "the project has more than 2 files"
    )
    assert inner.runs == 0


def test_the_size_limit_is_the_one_in_the_snapshot_module(
    tmp_path,
    monkeypatch,
) -> None:
    """The wrapper reads the limits when it runs, not when it is made."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_BYTES", 2)
    inner = Inner()

    outcome = ReadOnlyAdapter(inner).execute(
        _request(_project(tmp_path, 3)),
    )

    assert outcome.outcome == "failed"
    assert "more than 2 bytes in files" in outcome.reason
    assert inner.runs == 0


def test_a_run_that_grows_the_project_past_a_limit_fails(
    tmp_path,
    monkeypatch,
) -> None:
    """The second snapshot stops at the limit, and the run is a failure."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 3)
    project = _project(tmp_path, 1)

    def grow(path):
        for number in range(4):
            (path / f"new{number}.txt").write_bytes(b"y")

    inner = Inner(grow)

    outcome = ReadOnlyAdapter(inner).execute(_request(project))

    assert outcome.outcome == "failed"
    assert outcome.reason == (
        "the project passed a limit during the run, so the run could not "
        "be checked: the project has more than 3 files"
    )
    assert inner.runs == 1


def test_a_snapshot_that_is_passed_in_is_used_as_it_is(tmp_path) -> None:
    """A caller can still choose how the snapshots are taken."""
    taken = []

    def take(path):
        taken.append(path)

        return {}

    project = _project(tmp_path, 3)

    ReadOnlyAdapter(Inner(), take=take).execute(_request(project))

    assert taken == [project, project]


def test_the_attempt_of_the_outcome_is_kept_when_the_limit_stops_it(
    tmp_path,
    monkeypatch,
) -> None:
    """The failed outcome still names the attempt that the run started."""
    monkeypatch.setattr(snapshot_module, "SNAPSHOT_MAX_FILES", 3)
    project = _project(tmp_path, 1)

    def grow(path):
        for number in range(4):
            (path / f"new{number}.txt").write_bytes(b"y")

    outcome = ReadOnlyAdapter(Inner(grow, attempt_id="attempt-7")).execute(
        _request(project),
    )

    assert outcome.outcome == "failed"
    assert outcome.attempt_id == "attempt-7"
