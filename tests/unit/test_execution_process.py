"""Tests for the process adapter."""

import os
import signal
import subprocess
import sys
import time

import pytest

from aic_control_centre.execution import process as process_module
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.process import (
    ENVIRONMENT_ALLOWLIST,
    ProcessAdapter,
    child_environment,
)

REQUEST = ExecutionRequest(task_id="task-1", target="test")

ECHO_CHILD = """
import json, sys
request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
print(json.dumps({"outcome": "completed",
                  "reason": "ran %s on %s" % (request["task_id"],
                                              request["target"])}))
"""

FAILED_CHILD = """
import json
print(json.dumps({"outcome": "failed", "reason": "disk was full"}))
"""

UNICODE_CHILD = r"""
import json, sys
outcome = {"outcome": "completed", "reason": "caf\u00e9 \u2192 done"}
text = json.dumps(outcome, ensure_ascii=False)
sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
"""

SLEEP_CHILD = "import time; time.sleep(60)"

FLOOD_CHILD = """
import sys
while True:
    sys.stdout.write("x" * 1000)
    sys.stdout.flush()
"""

ERROR_FLOOD_CHILD = """
import sys
while True:
    sys.stderr.write("e" * 1000)
    sys.stderr.flush()
"""

EXIT_CHILD = """
import sys
sys.stderr.write("oops")
sys.exit(3)
"""

TREE_CHILD = """
import subprocess, sys, time
grandchild = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(120)"],
)
with open(sys.argv[1], "w") as handle:
    handle.write(str(grandchild.pid))
time.sleep(120)
"""

STRAGGLER_CHILD = """
import json, subprocess, sys
grandchild = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(120)"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
with open(sys.argv[1], "w") as handle:
    handle.write(str(grandchild.pid))
print(json.dumps({"outcome": "completed", "reason": "done"}))
"""

HOLDER_CHILD = """
import json, subprocess, sys
grandchild = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(30)"],
)
with open(sys.argv[1], "w") as handle:
    handle.write(str(grandchild.pid))
print(json.dumps({"outcome": "completed", "reason": "done"}), flush=True)
"""

ENV_CHILD = """
import json, os
reason = "secret=%s path=%s" % (
    os.environ.get("AIC_SECRET_TEST", "absent"),
    "PATH" in os.environ,
)
print(json.dumps({"outcome": "completed", "reason": reason}))
"""

CWD_CHILD = """
import json, os
print(json.dumps({"outcome": "completed", "reason": os.getcwd()}))
"""


def _adapter(code, *arguments, **settings):
    return ProcessAdapter([sys.executable, "-c", code, *arguments], **settings)


def _alive(pid):
    if os.name == "nt":
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
        ).stdout

        return str(pid) in listing

    try:
        with open(f"/proc/{pid}/stat") as handle:
            return handle.read().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False
    except OSError:
        pass

    try:
        os.kill(pid, 0)
    except OSError:
        return False

    return True


def _wait_dead(pid, seconds=10.0):
    deadline = time.monotonic() + seconds

    while time.monotonic() < deadline:
        if not _alive(pid):
            return True

        time.sleep(0.1)

    return not _alive(pid)


def _kill_pid(pid):
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
            )
        else:
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _read_pid(path):
    return int(path.read_text())


def test_valid_outcome_is_returned_and_the_request_reaches_the_child():
    """The child reads the request from stdin and its outcome is used."""
    outcome = _adapter(ECHO_CHILD).execute(REQUEST)

    assert outcome.task_id == "task-1"
    assert outcome.outcome == "completed"
    assert outcome.reason == "ran task-1 on test"


def test_a_failure_reported_by_the_child_is_passed_on():
    """A child can report failed, with its own reason."""
    outcome = _adapter(FAILED_CHILD).execute(REQUEST)

    assert outcome.outcome == "failed"
    assert outcome.reason == "disk was full"


def test_non_ascii_text_round_trips_as_utf8():
    """The reason survives the trip through the child's stdout."""
    outcome = _adapter(UNICODE_CHILD).execute(REQUEST)

    assert outcome.outcome == "completed"
    assert outcome.reason == "caf\u00e9 \u2192 done"


def test_a_child_that_runs_too_long_is_stopped_and_fails():
    """A timeout is a failed outcome that names the time."""
    started = time.monotonic()

    outcome = _adapter(SLEEP_CHILD, timeout_seconds=1).execute(REQUEST)

    assert outcome.outcome == "failed"
    assert outcome.reason == "adapter timed out after 1 seconds"
    assert time.monotonic() - started < 20


def test_timeout_stops_the_whole_process_tree(tmp_path):
    """A process the child started is dead too, not left running."""
    pidfile = tmp_path / "grandchild.pid"

    outcome = _adapter(
        TREE_CHILD,
        str(pidfile),
        timeout_seconds=4,
    ).execute(REQUEST)

    assert outcome.outcome == "failed"
    assert "timed out" in outcome.reason
    assert _wait_dead(_read_pid(pidfile))


@pytest.mark.skipif(os.name == "nt", reason="groups outlive their leader")
def test_processes_left_behind_by_a_finished_child_are_stopped(tmp_path):
    """After a normal exit, a straggler is stopped as well."""
    pidfile = tmp_path / "straggler.pid"

    outcome = _adapter(STRAGGLER_CHILD, str(pidfile)).execute(REQUEST)

    assert outcome.outcome == "completed"
    assert _wait_dead(_read_pid(pidfile))


def test_a_process_left_holding_the_output_does_not_hang_the_adapter(
    tmp_path,
    monkeypatch,
):
    """With no group to stop, a straggler on the pipe cannot block us."""
    monkeypatch.setattr(process_module, "_stop_group", lambda process: None)
    pidfile = tmp_path / "holder.pid"
    started = time.monotonic()

    try:
        outcome = _adapter(HOLDER_CHILD, str(pidfile)).execute(REQUEST)
        elapsed = time.monotonic() - started
    finally:
        if pidfile.exists() and pidfile.read_text():
            _kill_pid(_read_pid(pidfile))

    assert outcome.outcome == "completed"
    assert outcome.reason == "done"
    assert elapsed < 15


def test_output_over_the_limit_is_stopped_and_fails():
    """A child that never stops printing is cut off at the limit."""
    started = time.monotonic()

    outcome = _adapter(
        FLOOD_CHILD,
        stdout_limit=10000,
        timeout_seconds=30,
    ).execute(REQUEST)

    assert outcome.outcome == "failed"
    assert outcome.reason == "adapter output exceeded 10000 bytes"
    assert time.monotonic() - started < 20


def test_error_output_over_the_limit_is_stopped_and_fails():
    """The same limit applies to what the child writes to stderr."""
    outcome = _adapter(
        ERROR_FLOOD_CHILD,
        stderr_limit=5000,
        timeout_seconds=30,
    ).execute(REQUEST)

    assert outcome.outcome == "failed"
    assert outcome.reason.startswith("adapter error output exceeded 5000")


def test_a_failing_exit_status_fails_and_includes_stderr():
    """A non-zero exit is a failure, and stderr helps to diagnose it."""
    outcome = _adapter(EXIT_CHILD).execute(REQUEST)

    assert outcome.outcome == "failed"
    assert "adapter exited with status 3" in outcome.reason
    assert "stderr: oops" in outcome.reason


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("not json", "adapter output was not valid JSON"),
        ("[1, 2]", "adapter output was not a JSON object"),
        ('{"reason": "x"}', "adapter reported an unknown outcome"),
        ('{"outcome": "great"}', "adapter reported an unknown outcome"),
        (
            '{"outcome": "completed", "reason": 5}',
            "adapter reason was not text",
        ),
    ],
)
def test_output_that_breaks_the_contract_fails(text, expected):
    """Anything but one valid outcome object is a failed outcome."""
    outcome = _adapter(f"print({text!r})").execute(REQUEST)

    assert outcome.outcome == "failed"
    assert outcome.reason == expected


def test_a_very_long_reason_is_shortened():
    """A reason is kept short, whatever the child sends."""
    code = (
        "import json; "
        "print(json.dumps({'outcome': 'completed', 'reason': 'r' * 5000}))"
    )

    outcome = _adapter(code).execute(REQUEST)

    assert outcome.outcome == "completed"
    assert len(outcome.reason) == 1000
    assert outcome.reason.endswith("...")


def test_the_child_gets_only_the_allowed_environment(monkeypatch):
    """A secret in the parent's environment is not passed on."""
    monkeypatch.setenv("AIC_SECRET_TEST", "hunter2")

    outcome = _adapter(ENV_CHILD).execute(REQUEST)

    assert outcome.reason == "secret=absent path=True"


def test_child_environment_keeps_only_listed_names():
    """The allowlist is the whole of what a child inherits."""
    environ = {name: "value" for name in ENVIRONMENT_ALLOWLIST}
    environ["AWS_SECRET_ACCESS_KEY"] = "secret"
    environ["AIC_DATA_DIR"] = "/data"

    assert child_environment(environ) == {
        name: "value" for name in ENVIRONMENT_ALLOWLIST
    }


def test_the_child_runs_in_a_temporary_directory_that_is_removed():
    """The child does not run in the current directory."""
    outcome = _adapter(CWD_CHILD).execute(REQUEST)

    assert outcome.reason != os.getcwd()
    assert not os.path.exists(outcome.reason)


def test_an_interrupt_stops_the_process_tree(tmp_path, monkeypatch):
    """Ctrl-C in the parent must not leave the child running."""
    pidfile = tmp_path / "grandchild.pid"
    real_pause = process_module._pause

    def interrupt_once_the_tree_exists(seconds):
        if pidfile.exists() and pidfile.read_text():
            raise KeyboardInterrupt

        real_pause(seconds)

    monkeypatch.setattr(
        process_module,
        "_pause",
        interrupt_once_the_tree_exists,
    )

    with pytest.raises(KeyboardInterrupt):
        _adapter(
            TREE_CHILD,
            str(pidfile),
            timeout_seconds=60,
        ).execute(REQUEST)

    assert _wait_dead(_read_pid(pidfile))


@pytest.mark.parametrize(
    "arguments",
    [[], [""], ["python", 3], "", None],
)
def test_the_command_must_be_a_list_of_text(arguments):
    """An empty or malformed command is refused when it is built."""
    with pytest.raises((ValueError, TypeError)):
        ProcessAdapter(arguments)


@pytest.mark.parametrize(
    "settings",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": -1},
        {"stdout_limit": 0},
        {"stderr_limit": 0},
    ],
)
def test_limits_must_be_positive(settings):
    """A zero or negative limit is refused when the adapter is built."""
    with pytest.raises(ValueError):
        ProcessAdapter(["python"], **settings)
