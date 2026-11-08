"""Tests for removing the lock file that a killed owner left behind."""

import os

from aic_control_centre.execution import run_lock
from aic_control_centre.execution.run_lock import (
    RUN_LOCK_SUFFIX,
    RUNS_DIR_NAME,
    remove_run_lock_file,
)

ATTEMPT = "3f2a9c1e-5b7d-4e8a-9c3b-1d2e3f4a5b6c"


def _file(tmp_path, attempt_id):
    runs = tmp_path / RUNS_DIR_NAME
    runs.mkdir(exist_ok=True)
    (runs / (attempt_id + RUN_LOCK_SUFFIX)).write_bytes(b"")


def test_the_file_of_the_attempt_is_removed_and_no_other(tmp_path) -> None:
    _file(tmp_path, ATTEMPT)
    _file(tmp_path, "another-attempt")

    remove_run_lock_file(tmp_path, ATTEMPT)

    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        "another-attempt" + RUN_LOCK_SUFFIX,
    ]


def test_a_missing_file_is_not_an_error(tmp_path) -> None:
    remove_run_lock_file(tmp_path, ATTEMPT)

    assert os.listdir(tmp_path) == []


def test_an_id_that_is_not_a_safe_file_name_removes_nothing(
    tmp_path,
) -> None:
    (tmp_path / ("x" + RUN_LOCK_SUFFIX)).write_bytes(b"")
    _file(tmp_path, "other")

    remove_run_lock_file(tmp_path, "../x")
    remove_run_lock_file(tmp_path, "")

    assert os.path.lexists(tmp_path / ("x" + RUN_LOCK_SUFFIX))
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        "other" + RUN_LOCK_SUFFIX,
    ]


def test_a_file_that_cannot_be_removed_is_not_an_error(
    tmp_path,
    monkeypatch,
) -> None:
    _file(tmp_path, ATTEMPT)

    def refuse(path):
        raise PermissionError("in use")

    monkeypatch.setattr(run_lock.os, "remove", refuse)

    remove_run_lock_file(tmp_path, ATTEMPT)

    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        ATTEMPT + RUN_LOCK_SUFFIX,
    ]


def test_it_leaves_the_runs_directory_in_place(tmp_path) -> None:
    _file(tmp_path, ATTEMPT)

    remove_run_lock_file(tmp_path, ATTEMPT)

    assert os.listdir(tmp_path) == [RUNS_DIR_NAME]
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []
