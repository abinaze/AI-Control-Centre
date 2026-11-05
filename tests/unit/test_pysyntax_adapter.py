"""Tests for the shipped Python syntax check adapter."""

import importlib.util
import shutil
import sys
from pathlib import Path

import aic_control_centre
from aic_control_centre.execution.adapters import (
    PYSYNTAX_DESCRIPTION,
    PYSYNTAX_MODULE,
    PYSYNTAX_TARGET,
    build_adapter_registry,
    build_pysyntax_adapter,
)
from aic_control_centre.execution.check_python import (
    check_directory,
    describe,
)
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.process import ProcessAdapter
from aic_control_centre.execution.readonly import ReadOnlyAdapter


def _project(tmp_path, files):
    project = tmp_path / "project"
    project.mkdir()

    for name, text in files.items():
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    return project


def _listing(root):
    return sorted(
        (path.relative_to(root).as_posix(), path.is_file())
        for path in root.rglob("*")
    )


def _execute(adapter, project):
    return adapter.execute(
        ExecutionRequest(
            task_id="task-1",
            target=PYSYNTAX_TARGET,
            project_path=project,
        ),
    )


def test_the_target_is_pysyntax_and_the_module_exists() -> None:
    """The module that the adapter runs is the one that ships."""
    assert PYSYNTAX_TARGET == "pysyntax"
    assert PYSYNTAX_MODULE == "aic_control_centre.execution.check_python"
    assert importlib.util.find_spec(PYSYNTAX_MODULE) is not None


def test_the_shipped_registry_holds_pysyntax() -> None:
    """It is registered beside the others, and the names are sorted."""
    targets = build_adapter_registry().list_targets()

    assert "pysyntax" in targets
    assert targets == sorted(targets)


def test_pysyntax_is_a_read_only_process_that_needs_a_grant() -> None:
    """The adapter is wrapped, runs the shipped module, and needs both."""
    adapter = build_adapter_registry().resolve(PYSYNTAX_TARGET)

    assert isinstance(adapter, ReadOnlyAdapter)
    assert isinstance(adapter.adapter, ProcessAdapter)
    assert adapter.adapter.command == (
        sys.executable,
        "-B",
        "-m",
        PYSYNTAX_MODULE,
    )
    assert adapter.requires_grant is True
    assert adapter.adapter.requires_grant is True
    assert adapter.adapter.requires_project is True
    assert adapter.description == PYSYNTAX_DESCRIPTION
    assert PYSYNTAX_DESCRIPTION == (
        "checks the syntax of the Python files in the project directory; "
        "changes nothing"
    )


def test_a_run_on_a_clean_project_completes(tmp_path) -> None:
    """The reason is the description, and the task is the one asked."""
    project = _project(tmp_path, {"a.py": "x = 1\n", "pkg/b.py": "y = 2\n"})

    outcome = _execute(build_pysyntax_adapter(), project)

    assert outcome.task_id == "task-1"
    assert outcome.outcome == "completed"
    assert outcome.reason == describe(check_directory(project))
    assert "2 files checked, 0 with errors" in outcome.reason


def test_a_run_on_a_project_with_problems_fails_with_them(tmp_path) -> None:
    """The reason is the child's, and not a complaint about a change."""
    project = _project(tmp_path, {"ok.py": "x = 1\n", "bad.py": "def f(:\n"})

    outcome = _execute(build_pysyntax_adapter(), project)

    assert outcome.outcome == "failed"
    assert outcome.reason == describe(check_directory(project))
    assert "bad.py line 1: " in outcome.reason
    assert "changed during" not in outcome.reason


def test_a_run_leaves_the_project_as_it_was(tmp_path) -> None:
    """No bytecode, no marker, and the files are not run."""
    marker = tmp_path / "marker"
    project = _project(
        tmp_path,
        {
            "evil.py": f"open({str(marker)!r}, 'w').write('ran')\n",
            "pkg/__init__.py": "",
            "pkg/mod.py": "import evil\n",
        },
    )
    before = _listing(project)

    outcome = _execute(build_pysyntax_adapter(), project)

    assert outcome.outcome == "completed"
    assert not marker.exists()
    assert _listing(project) == before


def test_a_run_on_the_source_of_aic_itself_completes(tmp_path) -> None:
    """A real project of many files, checked by the Python that runs AIC."""
    source = Path(aic_control_centre.__file__).parent
    project = tmp_path / "copy"
    shutil.copytree(
        source,
        project,
        ignore=shutil.ignore_patterns("__pycache__"),
    )

    outcome = _execute(build_pysyntax_adapter(), project)

    assert outcome.outcome == "completed"
    assert "0 with errors" in outcome.reason
    assert " 0 files checked" not in outcome.reason
