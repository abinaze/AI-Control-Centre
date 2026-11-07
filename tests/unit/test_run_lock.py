"""Tests for the lock that shows whether the owner of an attempt is alive."""

import os
import subprocess
import sys
import threading
import time

import pytest

from aic_control_centre.execution import run_lock
from aic_control_centre.execution.run_lock import (
    MAX_ATTEMPT_ID_LENGTH,
    OWNER_ALIVE,
    OWNER_GONE,
    OWNER_UNKNOWN,
    RUN_LOCK_SUFFIX,
    RUNS_DIR_NAME,
    RunLockError,
    hold_run_lock,
    probe_run_lock,
    run_lock_path,
)

ATTEMPT = "3f2a9c1e-5b7d-4e8a-9c3b-1d2e3f4a5b6c"

UNSAFE_IDS = [
    "",
    " ",
    "a b",
    "a/b",
    "a\\b",
    "..",
    "../x",
    "x/../y",
    "a.b",
    "a:b",
    "id\n",
    "\u00e9",
    "x" * (MAX_ATTEMPT_ID_LENGTH + 1),
]

# A child that holds the lock and starts a grandchild of its own, the way
# a process adapter does, then waits to be killed.
_OWNER_CODE = """
import subprocess
import sys
import time
from pathlib import Path

from aic_control_centre.execution.run_lock import hold_run_lock

with hold_run_lock(Path(sys.argv[1]), sys.argv[2]):
    grandchild = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    print("held", grandchild.pid, flush=True)
    time.sleep(60)
"""


def _lines_of(process, count, seconds):
    """Read lines from a process in a thread, so that a hang is bounded."""
    lines = []

    def read():
        for _ in range(count):
            lines.append(process.stdout.readline().strip())

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(seconds)

    return lines


def _alive(pid):
    """Return whether a process exists, on a platform that has signals."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False

    return True


def test_the_lock_file_is_named_after_the_attempt(tmp_path) -> None:
    path = run_lock_path(tmp_path, ATTEMPT)

    assert path == tmp_path / RUNS_DIR_NAME / (ATTEMPT + RUN_LOCK_SUFFIX)
    assert RUNS_DIR_NAME == "runs"
    assert RUN_LOCK_SUFFIX == ".lock"


def test_the_three_answers_are_distinct_words() -> None:
    assert (OWNER_ALIVE, OWNER_GONE, OWNER_UNKNOWN) == (
        "alive",
        "gone",
        "unknown",
    )


@pytest.mark.parametrize("attempt_id", UNSAFE_IDS)
def test_an_attempt_id_that_is_not_a_safe_file_name_is_refused(
    tmp_path,
    attempt_id,
) -> None:
    with pytest.raises(RunLockError):
        run_lock_path(tmp_path, attempt_id)

    with pytest.raises(RunLockError):
        with hold_run_lock(tmp_path, attempt_id):
            raise AssertionError("the body must not run")

    assert probe_run_lock(tmp_path, attempt_id) == OWNER_UNKNOWN
    assert os.listdir(tmp_path) == []


def test_an_id_at_the_length_limit_is_accepted(tmp_path) -> None:
    attempt_id = "a" * MAX_ATTEMPT_ID_LENGTH

    assert run_lock_path(tmp_path, attempt_id).name == (
        attempt_id + RUN_LOCK_SUFFIX
    )


def test_holding_makes_the_directory_and_the_file(tmp_path) -> None:
    with hold_run_lock(tmp_path, ATTEMPT):
        assert os.listdir(tmp_path) == [RUNS_DIR_NAME]
        assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
            ATTEMPT + RUN_LOCK_SUFFIX,
        ]
        assert os.path.getsize(run_lock_path(tmp_path, ATTEMPT)) == 0


def test_holding_makes_a_missing_data_directory(tmp_path) -> None:
    data_dir = tmp_path / "not" / "yet"

    with hold_run_lock(data_dir, ATTEMPT):
        assert probe_run_lock(data_dir, ATTEMPT) == OWNER_ALIVE

    assert os.listdir(data_dir / RUNS_DIR_NAME) == []


def test_a_held_lock_is_alive(tmp_path) -> None:
    with hold_run_lock(tmp_path, ATTEMPT):
        assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_ALIVE


def test_the_file_is_removed_and_the_directory_stays(tmp_path) -> None:
    with hold_run_lock(tmp_path, ATTEMPT):
        pass

    assert os.listdir(tmp_path) == [RUNS_DIR_NAME]
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []
    assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_UNKNOWN


def test_the_lock_is_released_and_removed_when_the_body_raises(
    tmp_path,
) -> None:
    with pytest.raises(ValueError):
        with hold_run_lock(tmp_path, ATTEMPT):
            raise ValueError("the run failed")

    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []

    with hold_run_lock(tmp_path, ATTEMPT):
        assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_ALIVE


def test_a_file_that_nobody_holds_is_gone(tmp_path) -> None:
    runs = tmp_path / RUNS_DIR_NAME
    runs.mkdir()
    (runs / (ATTEMPT + RUN_LOCK_SUFFIX)).write_bytes(b"")

    assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_GONE


def test_probing_twice_gives_the_same_answer(tmp_path) -> None:
    runs = tmp_path / RUNS_DIR_NAME
    runs.mkdir()
    (runs / (ATTEMPT + RUN_LOCK_SUFFIX)).write_bytes(b"")

    first = probe_run_lock(tmp_path, ATTEMPT)
    second = probe_run_lock(tmp_path, ATTEMPT)

    assert (first, second) == (OWNER_GONE, OWNER_GONE)


def test_a_probe_does_not_keep_the_lock(tmp_path) -> None:
    runs = tmp_path / RUNS_DIR_NAME
    runs.mkdir()
    (runs / (ATTEMPT + RUN_LOCK_SUFFIX)).write_bytes(b"")

    probe_run_lock(tmp_path, ATTEMPT)

    with hold_run_lock(tmp_path, ATTEMPT, timeout=0.0):
        assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_ALIVE


def test_a_probe_of_nothing_creates_nothing(tmp_path) -> None:
    assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_UNKNOWN
    assert os.listdir(tmp_path) == []

    (tmp_path / RUNS_DIR_NAME).mkdir()

    assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_UNKNOWN
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []


def test_a_probe_in_a_missing_data_directory_is_unknown(tmp_path) -> None:
    missing = tmp_path / "no" / "such" / "directory"

    assert probe_run_lock(missing, ATTEMPT) == OWNER_UNKNOWN
    assert not os.path.lexists(missing)


def test_a_second_holder_is_refused_and_leaves_the_first_alone(
    tmp_path,
) -> None:
    with hold_run_lock(tmp_path, ATTEMPT):
        with pytest.raises(RunLockError, match="held by another process"):
            with hold_run_lock(tmp_path, ATTEMPT, timeout=0.05):
                raise AssertionError("the body must not run")

        assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
            ATTEMPT + RUN_LOCK_SUFFIX,
        ]
        assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_ALIVE

    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []


def test_two_attempts_do_not_disturb_each_other(tmp_path) -> None:
    with hold_run_lock(tmp_path, ATTEMPT):
        with hold_run_lock(tmp_path, "other-attempt"):
            assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_ALIVE
            assert probe_run_lock(tmp_path, "other-attempt") == OWNER_ALIVE

        assert probe_run_lock(tmp_path, "other-attempt") == OWNER_UNKNOWN
        assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_ALIVE


def test_holding_waits_for_a_lock_that_is_busy_for_a_moment(
    tmp_path,
    monkeypatch,
) -> None:
    real = run_lock._try_lock
    answers = [False, False, False]

    def busy_then_free(handle):
        if answers:
            return answers.pop()

        return real(handle)

    monkeypatch.setattr(run_lock, "_try_lock", busy_then_free)

    with hold_run_lock(tmp_path, ATTEMPT, timeout=5.0):
        assert answers == []
        assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_ALIVE


def test_holding_gives_up_when_the_lock_stays_busy(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(run_lock, "_try_lock", lambda handle: False)

    started = time.monotonic()

    with pytest.raises(RunLockError, match=r"waited 0\.1s"):
        with hold_run_lock(tmp_path, ATTEMPT, timeout=0.1):
            raise AssertionError("the body must not run")

    assert 0.05 <= time.monotonic() - started < 5.0


def test_a_data_directory_that_is_a_file_gives_a_run_lock_error(
    tmp_path,
) -> None:
    not_a_directory = tmp_path / "data"
    not_a_directory.write_text("a file", encoding="utf-8")

    with pytest.raises(RunLockError, match="cannot be made"):
        with hold_run_lock(not_a_directory, ATTEMPT):
            raise AssertionError("the body must not run")

    assert not_a_directory.read_text(encoding="utf-8") == "a file"


def test_a_file_that_cannot_be_removed_does_not_stop_the_end(
    tmp_path,
    monkeypatch,
) -> None:
    def refuse(path):
        raise PermissionError("in use")

    monkeypatch.setattr(run_lock.os, "remove", refuse)

    with hold_run_lock(tmp_path, ATTEMPT):
        pass

    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        ATTEMPT + RUN_LOCK_SUFFIX,
    ]
    assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_GONE


def test_a_killed_owner_leaves_a_lock_that_is_gone(tmp_path) -> None:
    if not hasattr(os, "kill") or os.name == "nt":
        # Nothing is checked on Windows. What a kill does to the lock there
        # is for a run on Windows to show.
        return

    owner = subprocess.Popen(
        [sys.executable, "-c", _OWNER_CODE, str(tmp_path), ATTEMPT],
        stdout=subprocess.PIPE,
        text=True,
    )
    grandchild = None

    try:
        lines = _lines_of(owner, 1, 60)

        assert lines and lines[0].startswith("held ")

        grandchild = int(lines[0].split()[1])

        assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_ALIVE

        owner.kill()
        owner.wait(timeout=30)

        assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_GONE
        assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
            ATTEMPT + RUN_LOCK_SUFFIX,
        ]
        # The child of the owner does not hold the lock, and it is still
        # running. Gone means that the owner ended, and no more.
        assert _alive(grandchild)
    finally:
        owner.kill()
        owner.wait(timeout=30)
        owner.stdout.close()

        if grandchild is not None:
            try:
                os.kill(grandchild, 9)
            except OSError:
                pass


def test_an_owner_that_ends_normally_leaves_no_file(tmp_path) -> None:
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from aic_control_centre.execution.run_lock import hold_run_lock\n"
        "with hold_run_lock(Path(sys.argv[1]), sys.argv[2]):\n"
        "    print('held', flush=True)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), ATTEMPT],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.stdout.strip() == "held"
    assert result.returncode == 0
    assert probe_run_lock(tmp_path, ATTEMPT) == OWNER_UNKNOWN
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []
