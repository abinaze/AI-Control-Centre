"""Tests for the inspect child process."""

import errno
import io
import json
import os
import subprocess
import sys
from types import SimpleNamespace

from aic_control_centre.execution import inspect_project as inspect_module
from aic_control_centre.execution.inspect_project import (
    PATH_LIMIT,
    describe,
    inspect_directory,
    main,
    run,
)
from aic_control_centre.execution.process import child_environment
from aic_control_centre.execution.snapshot import escape_name
from aic_control_centre.projects.directory import MISSING

MODULE = "aic_control_centre.execution.inspect_project"


def _request(**fields):
    return json.dumps(fields).encode("utf-8")


def _shown(path):
    """The path as a reason shows it: backslashes are doubled on Windows."""
    return escape_name(str(path), limit=PATH_LIMIT)


def _project(tmp_path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "README.md").write_bytes(b"hello")
    (project / "src" / "app.py").write_bytes(b"x" * 3000)

    return project


def test_a_request_that_is_not_utf8_is_refused() -> None:
    """The reason says what was wrong with the request."""
    assert run(b"\xff\xfe") == {
        "outcome": "failed",
        "reason": "the request was not valid UTF-8",
    }


def test_a_request_that_is_not_json_is_refused() -> None:
    """Text that is not JSON, and JSON nested too deeply, are refused."""
    expected = {
        "outcome": "failed",
        "reason": "the request was not valid JSON",
    }

    assert run(b"not json") == expected
    assert run(b"[" * 200000) == expected


def test_a_request_without_a_usable_path_is_refused() -> None:
    """The path must be a non-empty text in a JSON object."""
    expected = {
        "outcome": "failed",
        "reason": "the request has no project path",
    }

    assert run(b"[1]") == expected
    assert run(_request(task_id="t")) == expected
    assert run(_request(project_path="")) == expected
    assert run(_request(project_path=5)) == expected
    assert run(_request(project_path=None)) == expected


def test_a_missing_directory_is_reported_with_its_path(tmp_path) -> None:
    """The reason names the path."""
    missing = tmp_path / "gone"

    result = run(_request(project_path=str(missing)))

    assert result["outcome"] == "failed"
    assert result["reason"] == (
        f"the project directory does not exist: {_shown(missing)}"
    )


def test_a_path_that_is_a_file_is_reported(tmp_path) -> None:
    """A file is not a directory."""
    file = tmp_path / "file.txt"
    file.write_bytes(b"x")

    result = run(_request(project_path=str(file)))

    assert result["outcome"] == "failed"
    assert result["reason"] == (
        f"the project path is not a directory: {_shown(file)}"
    )


def test_a_directory_that_cannot_be_read_says_why(
    tmp_path,
    monkeypatch,
) -> None:
    """The reason that the system gave is in the reason."""
    real = os.stat

    def stat(path, *arguments, **options):
        if os.fspath(path) == str(tmp_path):
            raise OSError(errno.EACCES, "Permission denied")

        return real(path, *arguments, **options)

    monkeypatch.setattr(os, "stat", stat)

    result = run(_request(project_path=str(tmp_path)))

    assert result == {
        "outcome": "failed",
        "reason": (
            f"the project directory cannot be read: {_shown(tmp_path)}; "
            "Permission denied"
        ),
    }


def test_a_path_is_escaped_in_a_reason(monkeypatch) -> None:
    """The path is data, so it cannot move the cursor or hide text."""
    monkeypatch.setattr(
        inspect_module,
        "directory_problem",
        lambda path: (MISSING, ""),
    )

    result = run(_request(project_path="a\nb\x1b[2J"))

    assert result["reason"] == (
        "the project directory does not exist: a\\x0ab\\x1b[2J"
    )


def test_a_backslash_in_a_path_is_doubled_in_a_reason(monkeypatch) -> None:
    """A Windows path is shown with doubled backslashes, as names are."""
    monkeypatch.setattr(
        inspect_module,
        "directory_problem",
        lambda path: (MISSING, ""),
    )

    result = run(_request(project_path="C:\\Users\\me\\project"))

    assert result["reason"] == (
        "the project directory does not exist: "
        "C:\\\\Users\\\\me\\\\project"
    )


def test_an_error_during_the_walk_is_reported(tmp_path, monkeypatch) -> None:
    """An OSError from the walk becomes a failed outcome."""

    def refuse(root):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(inspect_module, "inspect_directory", refuse)

    result = run(_request(project_path=str(tmp_path)))

    assert result == {
        "outcome": "failed",
        "reason": "the project directory cannot be read: Input/output error",
    }


def test_a_project_is_described(tmp_path) -> None:
    """The reason is the description of what the walk found."""
    project = _project(tmp_path)

    result = run(_request(project_path=str(project), task_id="t"))

    assert result["outcome"] == "completed"
    assert result["reason"] == describe(inspect_directory(project))
    assert result["reason"] == (
        "inspected project: 2 files, 1 directories, 2.9 KiB; "
        "largest: src/app.py (2.9 KiB), README.md (5 B); "
        "README: yes; .git: no"
    )


def test_main_prints_one_json_line_and_returns_zero(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The answer goes to standard output, and the exit status is zero."""
    project = _project(tmp_path)
    monkeypatch.setattr(
        sys,
        "stdin",
        SimpleNamespace(
            buffer=io.BytesIO(_request(project_path=str(project))),
        ),
    )

    assert main() == 0

    lines = capsys.readouterr().out.splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0])["outcome"] == "completed"


def test_main_answers_a_failure_with_status_zero(
    monkeypatch,
    capsys,
) -> None:
    """A request that cannot be done is an answer, not a crash."""
    monkeypatch.setattr(
        sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO(b"not json")),
    )

    assert main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "outcome": "failed",
        "reason": "the request was not valid JSON",
    }


def _child(tmp_path, payload):
    """Run the module as the process adapter does: clean env, empty cwd."""
    workdir = tmp_path / "empty"
    workdir.mkdir()

    return subprocess.run(
        [sys.executable, "-m", MODULE],
        input=payload,
        capture_output=True,
        cwd=workdir,
        env=child_environment(),
        timeout=60,
    )


def test_the_module_runs_as_a_child_process(tmp_path) -> None:
    """It works with the environment and directory a child is given."""
    project = _project(tmp_path)

    done = _child(tmp_path, _request(project_path=str(project)))

    assert done.returncode == 0
    assert done.stderr == b""

    lines = done.stdout.decode("utf-8").splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "outcome": "completed",
        "reason": describe(inspect_directory(project)),
    }


def test_the_child_reports_a_missing_directory(tmp_path) -> None:
    """A failure is a JSON answer and a zero exit status."""
    missing = tmp_path / "gone"

    done = _child(tmp_path, _request(project_path=str(missing)))

    assert done.returncode == 0
    assert json.loads(done.stdout.decode("utf-8")) == {
        "outcome": "failed",
        "reason": f"the project directory does not exist: {_shown(missing)}",
    }


def test_the_child_refuses_bytes_that_are_not_utf8(tmp_path) -> None:
    """Even a request that is not text gets a JSON answer."""
    done = _child(tmp_path, b"\xff\xfe")

    assert done.returncode == 0
    assert json.loads(done.stdout.decode("utf-8"))["reason"] == (
        "the request was not valid UTF-8"
    )
