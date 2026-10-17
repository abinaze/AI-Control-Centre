"""Run an execution adapter's work in a child process, with limits.

An adapter that runs inside the CLI process cannot be stopped if it
hangs. A ProcessAdapter runs a fixed command in a child process instead,
and AIC stops that process itself when it takes too long, prints too
much, or is interrupted.

The contract with the child is small:

- The command is a fixed list of arguments written in code. Nothing from
  a task is ever placed in it, or in the child's environment.
- AIC writes one JSON object to the child's standard input, as UTF-8:
  ``{"task_id": ..., "target": ...}``.
- The child writes one JSON object to its standard output, as UTF-8, and
  exits with status 0: ``{"outcome": ..., "reason": ...}``.
- Anything else is a failed outcome: a non-zero exit, output that is not
  that object, an unknown outcome, too much output, or too much time.

The child gets a short list of environment variables and runs in a new
empty temporary directory that is removed afterwards. When it must be
stopped, its whole process tree is stopped, not only the process itself.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Sequence

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_FAILED,
    KNOWN_EXECUTION_OUTCOMES,
    ExecutionOutcome,
)

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_STDOUT_LIMIT = 1024 * 1024
DEFAULT_STDERR_LIMIT = 64 * 1024

KILL_WAIT_SECONDS = 5.0
READER_JOIN_SECONDS = 2.0
POLL_INTERVAL_SECONDS = 0.05
READ_CHUNK_BYTES = 4096
STDERR_REASON_CHARS = 300
MAX_REASON_CHARS = 1000

# The only variables a child inherits. Python can need the system root to
# start on Windows. Anything else, such as a token in the parent's
# environment, is not passed on.
ENVIRONMENT_ALLOWLIST = (
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
)


def child_environment(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Return the environment a child process is given."""
    source = os.environ if environ is None else environ

    return {
        name: source[name] for name in ENVIRONMENT_ALLOWLIST if name in source
    }


def _pause(seconds: float) -> None:
    """Wait between checks on the child. Tests replace this."""
    time.sleep(seconds)


def _group_arguments() -> dict:
    """Start the child in its own group, so its tree can be stopped."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}

    return {"start_new_session": True}


def _stop_group(process: subprocess.Popen) -> None:
    """Stop every process in the child's group, on platforms that have one."""
    if os.name == "nt":
        return

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass


def _kill_tree(process: subprocess.Popen) -> None:
    """Stop the child and every process it started, and reap the child."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
        )
    else:
        _stop_group(process)

    try:
        process.kill()
    except OSError:
        pass

    try:
        process.wait(timeout=KILL_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _read_limited(stream, limit, sink, exceeded) -> None:
    """Read a stream in chunks, and stop with a flag if it is too long."""
    try:
        while True:
            chunk = stream.read1(READ_CHUNK_BYTES)

            if not chunk:
                return

            room = limit - len(sink)

            if len(chunk) > room:
                sink.extend(chunk[:room])
                exceeded.set()
                return

            sink.extend(chunk)
    except (OSError, ValueError):
        return


def _start_reader(stream, limit, sink, exceeded) -> threading.Thread:
    reader = threading.Thread(
        target=_read_limited,
        args=(stream, limit, sink, exceeded),
        daemon=True,
    )
    reader.start()

    return reader


def _send(process: subprocess.Popen, payload: bytes) -> None:
    """Write the request to the child. A child that exits early is fine."""
    try:
        process.stdin.write(payload)
        process.stdin.close()
    except OSError:
        pass


def _shorten(text: str) -> str:
    if len(text) <= MAX_REASON_CHARS:
        return text

    return text[: MAX_REASON_CHARS - 3] + "..."


def _stderr_note(stderr: bytes) -> str:
    text = stderr.decode("utf-8", errors="replace").strip()

    if not text:
        return ""

    return f"; stderr: {text[:STDERR_REASON_CHARS]}"


def _parse_output(stdout: bytes) -> tuple[tuple[str, str] | None, str]:
    """Return the outcome and reason the child reported, or why not."""
    try:
        text = stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None, "adapter output was not valid UTF-8"

    try:
        data = json.loads(text)
    except ValueError:
        return None, "adapter output was not valid JSON"

    if not isinstance(data, dict):
        return None, "adapter output was not a JSON object"

    outcome = data.get("outcome")

    if not isinstance(outcome, str) or outcome not in KNOWN_EXECUTION_OUTCOMES:
        return None, "adapter reported an unknown outcome"

    reason = data.get("reason", "")

    if not isinstance(reason, str):
        return None, "adapter reason was not text"

    return (outcome, reason), ""


class ProcessAdapter:
    """An execution adapter that runs a fixed command in a child process."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        description: str = "",
        requires_grant: bool = True,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        stdout_limit: int = DEFAULT_STDOUT_LIMIT,
        stderr_limit: int = DEFAULT_STDERR_LIMIT,
    ) -> None:
        arguments = tuple(command)

        if not arguments or not all(
            isinstance(argument, str) and argument for argument in arguments
        ):
            raise ValueError("command must be a list of non-empty strings")

        if timeout_seconds <= 0:
            raise ValueError("timeout must be greater than zero")

        if stdout_limit <= 0 or stderr_limit <= 0:
            raise ValueError("output limits must be greater than zero")

        self.command = arguments
        self.description = description
        self.requires_grant = requires_grant
        self.timeout_seconds = timeout_seconds
        self.stdout_limit = stdout_limit
        self.stderr_limit = stderr_limit

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        """Run the command for a request and return what it reported."""
        payload = json.dumps(
            {"task_id": request.task_id, "target": request.target},
        ).encode("utf-8")

        with tempfile.TemporaryDirectory(
            prefix="aic-run-",
            ignore_cleanup_errors=True,
        ) as workdir:
            return self._run(request, payload, workdir)

    def _run(
        self,
        request: ExecutionRequest,
        payload: bytes,
        workdir: str,
    ) -> ExecutionOutcome:
        process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workdir,
            env=child_environment(),
            **_group_arguments(),
        )
        stdout = bytearray()
        stderr = bytearray()
        stdout_over = threading.Event()
        stderr_over = threading.Event()
        readers = [
            _start_reader(
                process.stdout,
                self.stdout_limit,
                stdout,
                stdout_over,
            ),
            _start_reader(
                process.stderr,
                self.stderr_limit,
                stderr,
                stderr_over,
            ),
        ]

        try:
            _send(process, payload)
            problem = self._wait(process, stdout_over, stderr_over)
        finally:
            if process.poll() is None:
                _kill_tree(process)

            _stop_group(process)

            # A process that was left behind can hold a pipe open. Closing a
            # pipe that a reader is still blocked on would wait forever, so
            # only the pipes whose reader has finished are closed.
            streams = (process.stdout, process.stderr)

            for reader, stream in zip(readers, streams):
                reader.join(READER_JOIN_SECONDS)

                if not reader.is_alive():
                    stream.close()

        if problem is None and stdout_over.is_set():
            problem = f"adapter output exceeded {self.stdout_limit} bytes"

        if problem is None and stderr_over.is_set():
            problem = (
                f"adapter error output exceeded {self.stderr_limit} bytes"
            )

        if problem is None and process.returncode != 0:
            problem = f"adapter exited with status {process.returncode}"

        if problem is None:
            reported, problem = _parse_output(bytes(stdout))

            if reported is not None:
                return ExecutionOutcome(
                    task_id=request.task_id,
                    outcome=reported[0],
                    reason=_shorten(reported[1]),
                )

        return ExecutionOutcome(
            task_id=request.task_id,
            outcome=EXECUTION_OUTCOME_FAILED,
            reason=_shorten(problem + _stderr_note(bytes(stderr))),
        )

    def _wait(self, process, stdout_over, stderr_over) -> str | None:
        """Wait for the child, and say why it had to be stopped, if it was."""
        deadline = time.monotonic() + self.timeout_seconds

        while True:
            if process.poll() is not None:
                return None

            if stdout_over.is_set():
                return f"adapter output exceeded {self.stdout_limit} bytes"

            if stderr_over.is_set():
                return (
                    f"adapter error output exceeded {self.stderr_limit} bytes"
                )

            if time.monotonic() >= deadline:
                return (
                    f"adapter timed out after {self.timeout_seconds:g} seconds"
                )

            _pause(POLL_INTERVAL_SECONDS)
