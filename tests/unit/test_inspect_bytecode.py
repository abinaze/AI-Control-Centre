"""Tests that the inspect child does not write bytecode into a project.

When the project is the directory that AIC is installed from, the child
imports its own module from the project. Python would then write the
bytecode of that module there, and the read-only check would fail the run.
These tests use a child that imports a module from the project, started
with the flags that the real inspect adapter uses.
"""

import py_compile

from aic_control_centre.execution.adapters import (
    INSPECT_MODULE,
    build_inspect_adapter,
)
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.process import ProcessAdapter
from aic_control_centre.execution.readonly import ReadOnlyAdapter

CHILD = (
    "import json, sys\n"
    "project = json.loads(sys.stdin.read())['project_path']\n"
    "sys.path.insert(0, project + '/lib')\n"
    "import helper\n"
    "print(json.dumps({'outcome': 'completed', 'reason': helper.WORD}))\n"
)


def _flags():
    """Return the arguments that the inspect adapter puts before -m."""
    command = build_inspect_adapter().adapter.command

    assert command[-2:] == ("-m", INSPECT_MODULE)

    return list(command[:-2])


def _project(tmp_path):
    project = tmp_path / "project"
    (project / "lib").mkdir(parents=True)
    (project / "lib" / "helper.py").write_text(
        "WORD = 'one'\n",
        encoding="utf-8",
    )

    return project


def _run(project):
    inner = ProcessAdapter(
        [*_flags(), "-c", CHILD],
        requires_project=True,
    )
    request = ExecutionRequest(
        task_id="task-1",
        target="inspect",
        project_path=project,
    )

    return ReadOnlyAdapter(inner).execute(request)


def _caches(project):
    return sorted(
        path.relative_to(project).as_posix()
        for path in project.rglob("__pycache__")
    )


def test_the_inspect_child_is_started_without_writing_bytecode() -> None:
    """The flag is in the command that AIC ships, before the module."""
    assert "-B" in _flags()


def test_a_child_that_imports_from_the_project_leaves_no_bytecode(
    tmp_path,
) -> None:
    """The module is imported, and the project has no new file."""
    project = _project(tmp_path)

    outcome = _run(project)

    assert outcome.outcome == "completed"
    assert outcome.reason == "one"
    assert _caches(project) == []


def test_stale_bytecode_in_the_project_is_left_as_it_was(tmp_path) -> None:
    """A changed source does not make the child rewrite the bytecode."""
    project = _project(tmp_path)
    source = project / "lib" / "helper.py"
    cached = py_compile.compile(str(source), doraise=True)
    old_bytes = open(cached, "rb").read()
    source.write_text("WORD = 'two, longer'\n", encoding="utf-8")

    outcome = _run(project)

    assert outcome.outcome == "completed"
    assert outcome.reason == "two, longer"
    assert open(cached, "rb").read() == old_bytes
