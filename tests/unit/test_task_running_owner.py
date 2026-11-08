"""Tests for the Owner line of aic task running."""

import os
import subprocess
import sys
import threading
from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from aic_control_centre.cli import main
from aic_control_centre.execution.records import ExecutionRecord
from aic_control_centre.execution.run_lock import (
    RUN_LOCK_SUFFIX,
    RUNS_DIR_NAME,
    hold_run_lock,
)
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.running import OWNER_TEXT

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
EARLIER = "2026-10-19T09:00:00+00:00"
LATER = "2026-10-19T11:30:00+00:00"

_HOLDER = (
    "import sys, time\n"
    "from pathlib import Path\n"
    "from aic_control_centre.execution.run_lock import hold_run_lock\n"
    "with hold_run_lock(Path(sys.argv[1]), sys.argv[2]):\n"
    "    print('held', flush=True)\n"
    "    time.sleep(60)\n"
)


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr("aic_control_centre.tasks.commands._now", lambda: NOW)


def _task(task_id):
    return Task(
        id=task_id,
        goal_id="goal-1",
        title=f"title {task_id}",
        description="",
        status="running",
        created_at="2026-10-01T00:00:00+00:00",
        updated_at=EARLIER,
    )


def _record(task_id, attempt_id, started_at=EARLIER, source="coordinator"):
    return ExecutionRecord(
        id=attempt_id,
        task_id=task_id,
        source=source,
        target="noop" if source == "coordinator" else None,
        started_at=started_at,
        ended_at=None,
        ended_as=None,
        reason="",
    )


def _state(tmp_path, tasks, records):
    write_text_atomic(
        tmp_path / "tasks.json",
        serialize_state_items("tasks", [asdict(task) for task in tasks]),
    )
    write_text_atomic(
        tmp_path / "executions.json",
        serialize_state_items(
            "executions",
            [asdict(record) for record in records],
        ),
    )


def _free_lock_file(tmp_path, attempt_id):
    runs = tmp_path / RUNS_DIR_NAME
    runs.mkdir(exist_ok=True)
    (runs / (attempt_id + RUN_LOCK_SUFFIX)).write_bytes(b"")


def _owner_lines(output):
    """Return the owner line of each listed task, by task id."""
    owners = {}
    current = None

    for line in output.splitlines():
        if line.startswith("- "):
            current = line[2:].strip()
        elif line.startswith("  Owner: "):
            owners[current] = line[len("  Owner: "):]

    return owners


def test_a_live_owner_is_shown_as_alive(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])

    with hold_run_lock(tmp_path, "attempt-1"):
        result = run_cli(monkeypatch, tmp_path, "task", "running")

    output = capsys.readouterr().out

    assert result == 0
    assert f"  Owner: {OWNER_TEXT['alive']}" in output
    assert "the aic process that runs it holds its lock" in output


def test_a_dead_owner_is_shown_as_gone_with_the_child_warning(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])
    _free_lock_file(tmp_path, "attempt-1")

    result = run_cli(monkeypatch, tmp_path, "task", "running")

    output = capsys.readouterr().out

    assert result == 0
    assert f"  Owner: {OWNER_TEXT['gone']}" in output
    assert "its child may still be running" in output


def test_a_run_with_no_lock_is_shown_as_unknown(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _state(
        tmp_path,
        [_task("t1")],
        [_record("t1", "attempt-1", source="cli")],
    )

    run_cli(monkeypatch, tmp_path, "task", "running")

    output = capsys.readouterr().out

    assert f"  Owner: {OWNER_TEXT['unknown']}" in output
    assert "no lock was recorded for this run" in output


def test_every_task_shows_its_own_owner(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _state(
        tmp_path,
        [_task("t1"), _task("t2"), _task("t3")],
        [
            _record("t1", "attempt-1"),
            _record("t2", "attempt-2", started_at=LATER),
            _record("t3", "attempt-3", started_at="2026-10-19T08:00:00+00:00",
                    source="cli"),
        ],
    )
    _free_lock_file(tmp_path, "attempt-1")

    with hold_run_lock(tmp_path, "attempt-2"):
        run_cli(monkeypatch, tmp_path, "task", "running")

    owners = _owner_lines(capsys.readouterr().out)

    assert owners == {
        "t1": OWNER_TEXT["gone"],
        "t2": OWNER_TEXT["alive"],
        "t3": OWNER_TEXT["unknown"],
    }


def test_the_owner_line_follows_the_running_for_line(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])

    run_cli(monkeypatch, tmp_path, "task", "running")

    lines = capsys.readouterr().out.splitlines()
    index = lines.index("  Running for: 3h 0m")

    assert lines[index + 1].startswith("  Owner: ")
    assert lines[index + 2] == ""


def test_the_filter_keeps_the_owner_line(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])
    _free_lock_file(tmp_path, "attempt-1")

    run_cli(monkeypatch, tmp_path, "task", "running", "--older-than", "1h")

    assert _owner_lines(capsys.readouterr().out) == {
        "t1": OWNER_TEXT["gone"],
    }


def test_the_command_still_changes_nothing_and_makes_no_directory(
    tmp_path,
    monkeypatch,
) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])
    before = {
        name: (tmp_path / name).read_bytes() for name in os.listdir(tmp_path)
    }

    run_cli(monkeypatch, tmp_path, "task", "running")

    after = {
        name: (tmp_path / name).read_bytes() for name in os.listdir(tmp_path)
    }

    assert after == before
    assert not os.path.lexists(tmp_path / RUNS_DIR_NAME)


def _first_line(process, seconds):
    lines = []

    def read():
        lines.append(process.stdout.readline().strip())

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(seconds)

    return lines[0] if lines else ""


def test_a_real_owner_is_alive_until_it_is_killed_and_then_gone(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _state(tmp_path, [_task("t1")], [_record("t1", "attempt-1")])

    owner = subprocess.Popen(
        [sys.executable, "-B", "-c", _HOLDER, str(tmp_path), "attempt-1"],
        stdout=subprocess.PIPE,
        text=True,
    )

    try:
        assert _first_line(owner, 60) == "held"

        run_cli(monkeypatch, tmp_path, "task", "running")
        alive = _owner_lines(capsys.readouterr().out)

        owner.kill()
        owner.wait(timeout=30)

        run_cli(monkeypatch, tmp_path, "task", "running")
        gone = _owner_lines(capsys.readouterr().out)
    finally:
        owner.kill()
        owner.wait(timeout=30)
        owner.stdout.close()

    assert alive == {"t1": OWNER_TEXT["alive"]}
    assert gone == {"t1": OWNER_TEXT["gone"]}
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        "attempt-1" + RUN_LOCK_SUFFIX,
    ]
