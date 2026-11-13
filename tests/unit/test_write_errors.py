"""Tests for a state file that cannot be written.

An error that the file system gives for a write is reported as a
StateFileError that names the file and the reason, so that the command
line prints an Error line and not a traceback (G25). Most tests make the
write fail by patching os.replace, because a real read-only file stops a
replace on Windows and not on Linux.
"""

import os
import re
import sys
from pathlib import Path

import pytest

from aic_control_centre import storage
from aic_control_centre.cli import main
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.storage import StateFileError, write_text_atomic

DENIED = "Access is denied"


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _id(output):
    return re.search(r"^ID: (\S+)", output, re.M).group(1)


def _denying(*names):
    """Return an os.replace that is refused for the files with these names.

    The error has the shape that Windows gives for a read-only file.
    """
    real_replace = os.replace

    def replace(source, destination):
        if os.path.basename(destination) in names:
            raise PermissionError(
                13, DENIED, str(source), None, str(destination),
            )

        real_replace(source, destination)

    return replace


def _started(tmp_path, monkeypatch, capsys):
    """Return the data directory and the id of a task that was started."""
    data = tmp_path / "data"
    project = tmp_path / "project"
    data.mkdir()
    project.mkdir()

    assert run_cli(monkeypatch, data, "project", "add", str(project)) == 0
    assert run_cli(
        monkeypatch, data, "goal", "create", "--project", project.name, "g",
    ) == 0
    goal = _id(capsys.readouterr().out)
    assert run_cli(
        monkeypatch, data, "task", "create", "--goal", goal, "the task",
    ) == 0
    task = _id(capsys.readouterr().out)
    assert run_cli(monkeypatch, data, "task", "ready", task) == 0

    return data, task


def _status(data, task):
    text = (data / "tasks.json").read_text(encoding="utf-8")

    return re.search(r'"status": "(\w+)"', text).group(1)


def _error_line(output):
    lines = output.splitlines()

    assert lines
    assert lines[-1].startswith("Error: ")

    return lines[-1]


def test_a_refused_replace_is_an_error_that_names_the_file_and_why(
    tmp_path,
    monkeypatch,
) -> None:
    """The message has the file and the reason, and no temporary name.

    The refusal is simulated, in the shape that Windows gives.
    """
    target = tmp_path / "state.json"
    target.write_text("original", encoding="utf-8")
    monkeypatch.setattr(storage.os, "replace", _denying("state.json"))

    with pytest.raises(StateFileError) as caught:
        write_text_atomic(target, "replacement")

    assert str(caught.value) == f"{target} cannot be written: {DENIED}"
    assert isinstance(caught.value.__cause__, PermissionError)
    assert target.read_text(encoding="utf-8") == "original"
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


def test_an_error_with_only_a_message_gives_that_message(
    tmp_path,
    monkeypatch,
) -> None:
    """An OSError with no strerror still says why."""
    target = tmp_path / "state.json"

    def fail(descriptor):
        raise OSError("simulated failure")

    monkeypatch.setattr(storage.os, "fsync", fail)

    with pytest.raises(StateFileError) as caught:
        write_text_atomic(target, "replacement")

    assert str(caught.value) == (
        f"{target} cannot be written: simulated failure"
    )
    assert not list(tmp_path.iterdir())


def test_an_error_with_no_text_is_named_by_its_type(
    tmp_path,
    monkeypatch,
) -> None:
    """An OSError with no text at all is named by its class."""
    target = tmp_path / "state.json"

    def fail(descriptor):
        raise OSError()

    monkeypatch.setattr(storage.os, "fsync", fail)

    with pytest.raises(StateFileError) as caught:
        write_text_atomic(target, "replacement")

    assert str(caught.value) == f"{target} cannot be written: OSError"


def test_a_missing_directory_is_an_error_that_names_the_file(
    tmp_path,
) -> None:
    """The directory is still not created, and the error is a clean one."""
    target = tmp_path / "missing" / "state.json"

    with pytest.raises(StateFileError) as caught:
        write_text_atomic(target, "content")

    assert str(caught.value).startswith(f"{target} cannot be written: ")
    assert isinstance(caught.value.__cause__, FileNotFoundError)
    assert not (tmp_path / "missing").exists()


def test_a_cleanup_that_fails_does_not_hide_the_error(
    tmp_path,
    monkeypatch,
) -> None:
    """If the temporary file cannot be removed, the first error stands."""
    target = tmp_path / "state.json"
    monkeypatch.setattr(storage.os, "replace", _denying("state.json"))

    def refuse(self, missing_ok=False):
        raise PermissionError(13, DENIED, str(self))

    monkeypatch.setattr(Path, "unlink", refuse)

    with pytest.raises(StateFileError) as caught:
        write_text_atomic(target, "replacement")

    assert str(caught.value) == f"{target} cannot be written: {DENIED}"


def test_an_error_that_is_not_an_os_error_is_not_wrapped(tmp_path) -> None:
    """Only an error of the file system becomes a state file error."""
    target = tmp_path / "state.json"
    target.write_text("original", encoding="utf-8")

    with pytest.raises(UnicodeEncodeError):
        write_text_atomic(target, "\u00e9", encoding="ascii")

    assert target.read_text(encoding="utf-8") == "original"
    assert [path.name for path in tmp_path.iterdir()] == ["state.json"]


def test_a_directory_that_cannot_be_written_is_an_error(tmp_path) -> None:
    """Use a real directory with no write permission.

    This checks nothing on Windows, where a directory permission does not
    stop a file from being created, and nothing for the user root, which
    ignores directory permissions.
    """
    if os.name != "posix" or os.geteuid() == 0:
        return

    directory = tmp_path / "locked"
    directory.mkdir()
    directory.chmod(0o500)

    try:
        with pytest.raises(StateFileError, match="cannot be written"):
            write_text_atomic(directory / "state.json", "content")
    finally:
        directory.chmod(0o700)


def test_a_project_that_cannot_be_saved_gives_an_error_line(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The command ends with Error and exit status 1, not a traceback."""
    data = tmp_path / "data"
    project = tmp_path / "project"
    data.mkdir()
    project.mkdir()

    with monkeypatch.context() as patched:
        patched.setattr(storage.os, "replace", _denying("projects.json"))

        result = run_cli(patched, data, "project", "add", str(project))

    captured = capsys.readouterr()

    assert result == 1
    assert len(captured.out.splitlines()) == 1
    assert _error_line(captured.out).endswith(
        f"projects.json cannot be written: {DENIED}",
    )
    assert captured.err == ""
    assert not (data / "projects.json").exists()
    assert not [name for name in os.listdir(data) if name.endswith(".tmp")]


def test_a_start_that_cannot_open_its_record_leaves_the_task_ready(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The record is written first, so the task has not moved."""
    data, task = _started(tmp_path, monkeypatch, capsys)

    with monkeypatch.context() as patched:
        patched.setattr(storage.os, "replace", _denying("executions.json"))

        result = run_cli(patched, data, "task", "start", task)

    captured = capsys.readouterr()

    assert result == 1
    assert _error_line(captured.out).endswith(
        f"executions.json cannot be written: {DENIED}",
    )
    assert captured.err == ""
    assert _status(data, task) == "ready"


def test_a_finish_that_cannot_close_its_record_gives_an_error_line(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """This is the case that was found on Windows, simulated here.

    The task is completed and its attempt stays open. The error line
    appears, and aic task close-attempt closes the attempt afterwards.
    """
    data, task = _started(tmp_path, monkeypatch, capsys)
    assert run_cli(monkeypatch, data, "task", "start", task) == 0
    capsys.readouterr()

    with monkeypatch.context() as patched:
        patched.setattr(storage.os, "replace", _denying("executions.json"))

        result = run_cli(
            patched, data, "task", "complete", task, "--reason", "done",
        )

    captured = capsys.readouterr()

    assert result == 1
    assert "Status: completed" in captured.out.splitlines()
    assert _error_line(captured.out).endswith(
        f"executions.json cannot be written: {DENIED}",
    )
    assert captured.err == ""
    assert _status(data, task) == "completed"

    records = ExecutionRecordRegistry.beside(data / "tasks.json")

    assert [record.ended_at for record in records.list_attempts(task)] == [
        None,
    ]
    assert run_cli(monkeypatch, data, "validate") == 1
    capsys.readouterr()

    closed = run_cli(
        monkeypatch, data, "task", "close-attempt", task,
        "--reason", "the file could not be written",
    )

    assert closed == 0
    assert run_cli(monkeypatch, data, "validate") == 0
