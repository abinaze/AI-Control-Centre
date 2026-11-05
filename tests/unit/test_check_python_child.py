"""Tests for the child process of the Python syntax check."""

import errno
import io
import json
import subprocess
import sys

from aic_control_centre.execution import check_python as check_module
from aic_control_centre.execution.check_python import (
    check_directory,
    describe,
    main,
    python_version,
    run,
)
from aic_control_centre.execution.child_request import PATH_LIMIT
from aic_control_centre.execution.process import child_environment
from aic_control_centre.execution.snapshot import escape_name
from aic_control_centre.projects.directory import MISSING

MODULE = "aic_control_centre.execution.check_python"


def _request(**fields):
    return json.dumps(fields).encode("utf-8")


def _shown(path):
    """The path as a reason shows it: backslashes are doubled on Windows."""
    return escape_name(str(path), limit=PATH_LIMIT)


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


def test_a_project_without_problems_completes(tmp_path) -> None:
    """The reason is the description of the report."""
    project = _project(
        tmp_path,
        {"a.py": "x = 1\n", "pkg/b.py": "y = 2\n", "README.md": "hi"},
    )

    result = run(_request(project_path=str(project)))

    assert result == {
        "outcome": "completed",
        "reason": describe(check_directory(project)),
    }
    assert result["reason"] == (
        f"checked Python syntax with Python {python_version()}: "
        "2 files checked, 0 with errors, 0 too large, 0 not read, "
        "0 directories skipped"
    )


def test_a_project_with_problems_fails_and_names_them(tmp_path) -> None:
    """The outcome is failed, and the reason shows the first problems."""
    project = _project(
        tmp_path,
        {
            "ok.py": "x = 1\n",
            "bad.py": "def f(:\n",
            "pkg/worse.py": "return 1\n",
        },
    )

    result = run(_request(project_path=str(project)))

    assert result["outcome"] == "failed"
    assert result["reason"] == describe(check_directory(project))
    assert "3 files checked, 2 with errors" in result["reason"]
    assert "bad.py line 1: " in result["reason"]
    assert "pkg/worse.py line 1: " in result["reason"]


def test_a_project_with_no_python_files_completes(tmp_path) -> None:
    """Nothing to check is not a failure, and the reason says so."""
    project = _project(tmp_path, {"README.md": "hi"})

    result = run(_request(project_path=str(project)))

    assert result["outcome"] == "completed"
    assert "0 files checked" in result["reason"]


def test_a_project_that_is_too_big_fails_with_the_limit(
    tmp_path,
    monkeypatch,
) -> None:
    """A limit on the whole check is a failure that names the limit."""
    monkeypatch.setattr(check_module, "MAX_FILES", 1)
    project = _project(tmp_path, {"a.py": "x = 1\n", "b.py": "y = 2\n"})

    result = run(_request(project_path=str(project)))

    assert result == {
        "outcome": "failed",
        "reason": (
            f"checked Python syntax with Python {python_version()}: "
            "stopped: too many Python files: more than 1"
        ),
    }


def test_an_error_while_walking_is_a_failure_with_a_reason(
    tmp_path,
    monkeypatch,
) -> None:
    """The reason of the system is in the answer."""
    project = _project(tmp_path, {"a.py": "x = 1\n"})

    def refuse(root):
        raise OSError(errno.EIO, "disk error")

    monkeypatch.setattr(check_module, "check_directory", refuse)

    result = run(_request(project_path=str(project)))

    assert result == {
        "outcome": "failed",
        "reason": "the project directory cannot be read: disk error",
    }


def test_a_request_that_cannot_be_done_is_a_failed_answer(tmp_path) -> None:
    """The shared reader gives the texts, and nothing is checked."""
    gone = tmp_path / "gone"
    afile = tmp_path / "afile.py"
    afile.write_bytes(b"x = 1\n")

    assert run(b"\xff") == {
        "outcome": "failed",
        "reason": "the request was not valid UTF-8",
    }
    assert run(_request(task_id="t")) == {
        "outcome": "failed",
        "reason": "the request has no project path",
    }
    assert run(_request(project_path=str(gone))) == {
        "outcome": "failed",
        "reason": f"the project directory does not exist: {_shown(gone)}",
    }
    assert run(_request(project_path=str(afile))) == {
        "outcome": "failed",
        "reason": f"the project path is not a directory: {_shown(afile)}",
    }


def test_the_child_uses_its_own_check_of_the_directory(monkeypatch) -> None:
    """The check is looked up in this module, as it is in the other child."""
    monkeypatch.setattr(
        check_module,
        "directory_problem",
        lambda path: (MISSING, ""),
    )

    result = run(_request(project_path="a\nb\x1b[2J"))

    assert result == {
        "outcome": "failed",
        "reason": "the project directory does not exist: a\\x0ab\\x1b[2J",
    }


def test_main_prints_one_json_line_for_a_failure(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A project with a problem is an answer, so the status is zero."""
    project = _project(tmp_path, {"bad.py": "def f(:\n"})
    request = _request(project_path=str(project))

    class _Stdin:
        buffer = io.BytesIO(request)

    monkeypatch.setattr(sys, "stdin", _Stdin())

    assert main() == 0

    output = capsys.readouterr().out

    assert output == json.dumps(run(request)) + "\n"
    assert json.loads(output)["outcome"] == "failed"


def _child(tmp_path, payload):
    """Run the module as the adapter does: a child, with a clean setting."""
    workdir = tmp_path / "empty"
    workdir.mkdir(exist_ok=True)

    return subprocess.run(
        [sys.executable, "-B", "-m", MODULE],
        input=payload,
        capture_output=True,
        cwd=workdir,
        env=child_environment(),
        timeout=60,
    )


def test_the_module_runs_as_a_child_process(tmp_path) -> None:
    """It works with the environment and directory a child is given."""
    project = _project(tmp_path, {"a.py": "x = 1\n", "bad.py": "def f(:\n"})
    before = _listing(project)

    done = _child(tmp_path, _request(project_path=str(project)))

    assert done.returncode == 0
    assert done.stderr == b""

    lines = done.stdout.decode("utf-8").splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0]) == run(_request(project_path=str(project)))
    assert _listing(project) == before


def test_a_child_answers_a_bad_request_with_status_zero(tmp_path) -> None:
    """The parent reads an answer, and no traceback is printed."""
    done = _child(tmp_path, b"not json")

    assert done.returncode == 0
    assert done.stderr == b""
    assert json.loads(done.stdout) == {
        "outcome": "failed",
        "reason": "the request was not valid JSON",
    }


def test_a_file_that_only_warns_is_not_a_problem(tmp_path) -> None:
    """Warnings of the compiler are not printed and not errors."""
    project = _project(tmp_path, {"a.py": 'x = "\\d"\ny = 1 is 1\n'})

    done = _child(tmp_path, _request(project_path=str(project)))

    assert done.returncode == 0
    assert done.stderr == b""
    assert json.loads(done.stdout)["outcome"] == "completed"
