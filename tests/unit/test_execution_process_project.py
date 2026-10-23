"""Tests for the project path in the process adapter."""

import json
import sys

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.process import ProcessAdapter

DIRECTORY = "distinct-project-dir"

# The child reports short facts, never the whole environment. A reason is
# cut at 1000 characters, and PATH alone can be longer than that.
REPORT_CHILD = "needle = %r\n" % DIRECTORY + """
import json, os, sys
request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
report = {
    "keys": sorted(request),
    "path": request.get("project_path"),
    "argv": sys.argv[1:],
    "in_environment": any(needle in v for v in os.environ.values()),
    "in_cwd": needle in os.getcwd(),
}
print(json.dumps({"outcome": "completed", "reason": json.dumps(report)}))
"""


def _adapter(**options):
    return ProcessAdapter(
        [sys.executable, "-c", REPORT_CHILD],
        requires_grant=False,
        **options,
    )


def _report(adapter, project_path):
    outcome = adapter.execute(
        ExecutionRequest(
            task_id="task-1",
            target="test",
            project_path=project_path,
        ),
    )

    assert outcome.outcome == "completed", outcome.reason

    return json.loads(outcome.reason)


def test_requires_project_is_off_unless_it_is_asked_for() -> None:
    """The existing behaviour is the default."""
    assert _adapter().requires_project is False
    assert _adapter(requires_project=True).requires_project is True


def test_an_adapter_that_needs_a_project_sends_the_path(tmp_path) -> None:
    """The path reaches the child in the standard input JSON."""
    project = tmp_path / DIRECTORY
    project.mkdir()

    report = _report(_adapter(requires_project=True), project)

    assert report["path"] == str(project)
    assert report["keys"] == ["project_path", "target", "task_id"]


def test_the_path_is_not_in_the_command_or_the_environment(tmp_path) -> None:
    """The path travels in one place only, the standard input."""
    project = tmp_path / DIRECTORY
    project.mkdir()

    report = _report(_adapter(requires_project=True), project)

    assert report["argv"] == []
    assert report["in_environment"] is False
    assert report["in_cwd"] is False


def test_an_adapter_that_needs_no_project_sends_no_path(tmp_path) -> None:
    """A path on the request is not passed to an adapter that did not ask."""
    project = tmp_path / DIRECTORY
    project.mkdir()

    report = _report(_adapter(), project)

    assert report["path"] is None
    assert report["keys"] == ["target", "task_id"]


def test_a_request_without_a_path_sends_none() -> None:
    """A request built by hand has no path to send."""
    report = _report(_adapter(), None)

    assert report["keys"] == ["target", "task_id"]


def test_an_adapter_that_needs_a_project_fails_without_a_path(
    tmp_path,
) -> None:
    """The child is not started when there is nothing to give it."""
    marker = tmp_path / "started"
    adapter = ProcessAdapter(
        [
            sys.executable,
            "-c",
            "import sys; open(sys.argv[1], 'w').close()",
            str(marker),
        ],
        requires_grant=False,
        requires_project=True,
    )

    outcome = adapter.execute(
        ExecutionRequest(task_id="task-1", target="test"),
    )

    assert outcome.outcome == "failed"
    assert outcome.reason == "the request has no project path"
    assert not marker.exists()


def test_a_path_with_spaces_and_other_characters_round_trips(
    tmp_path,
) -> None:
    """Spaces and non-ASCII text come back as the same path."""
    project = tmp_path / "my caf\u00e9 \u2192 project"
    project.mkdir()

    report = _report(_adapter(requires_project=True), project)

    assert report["path"] == str(project)
