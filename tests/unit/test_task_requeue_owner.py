"""Tests for what aic task requeue does with the owner of a run."""

import os
import subprocess
import sys
import threading

from aic_control_centre import locking
from aic_control_centre.cli import main
from aic_control_centre.execution import run_lock
from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.run_lock import (
    RUN_LOCK_SUFFIX,
    RUNS_DIR_NAME,
    hold_run_lock,
)
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry

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


def _running_task(tmp_path, monkeypatch):
    """Make a task that was started through the CLI, with an open attempt."""
    goal = Goal.create(description="Requeue goal", project="TestProject")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)

    task = Task.create(goal_id=goal.id, title="Requeue task")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    assert run_cli(monkeypatch, tmp_path, "task", "start", task.id) == 0

    return task, _attempt(tmp_path, task.id)


def _attempt(tmp_path, task_id):
    records = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")

    return records.get_open_attempt(task_id)


def _attempts(tmp_path, task_id):
    records = ExecutionRecordRegistry.beside(tmp_path / "tasks.json")

    return records.list_attempts(task_id)


def _status(tmp_path, task_id):
    return TaskRegistry(tmp_path / "tasks.json").get_task(task_id).status


def _free_lock_file(tmp_path, attempt_id):
    runs = tmp_path / RUNS_DIR_NAME
    runs.mkdir(exist_ok=True)
    (runs / (attempt_id + RUN_LOCK_SUFFIX)).write_bytes(b"")


def _requeue(monkeypatch, tmp_path, task):
    return run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "requeue",
        task.id,
        "--reason",
        "looks stuck",
    )


def _state_bytes(tmp_path):
    return {
        name: (tmp_path / name).read_bytes()
        for name in os.listdir(tmp_path)
        if os.path.isfile(tmp_path / name) and not name.startswith(".")
    }


def test_a_run_whose_owner_is_alive_is_not_requeued(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task, attempt = _running_task(tmp_path, monkeypatch)
    before = _state_bytes(tmp_path)
    capsys.readouterr()

    with hold_run_lock(tmp_path, attempt.id):
        result = _requeue(monkeypatch, tmp_path, task)

        assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
            attempt.id + RUN_LOCK_SUFFIX,
        ]

    output = capsys.readouterr().out

    assert result == 1
    assert output.strip() == (
        f"Error: the run of task {task.id} is still alive: the aic process "
        "that runs it holds its lock. Wait for it to end, or stop that "
        "process, and then requeue."
    )
    assert _status(tmp_path, task.id) == "running"
    assert _attempt(tmp_path, task.id).id == attempt.id
    assert _state_bytes(tmp_path) == before


def test_the_refusal_names_no_dead_run(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task, attempt = _running_task(tmp_path, monkeypatch)
    capsys.readouterr()

    with hold_run_lock(tmp_path, attempt.id):
        _requeue(monkeypatch, tmp_path, task)

    output = capsys.readouterr().out

    assert "dead" not in output
    assert "stale" not in output
    assert "Previous status" not in output


def test_a_run_whose_owner_is_gone_is_requeued_and_its_file_removed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task, attempt = _running_task(tmp_path, monkeypatch)
    _free_lock_file(tmp_path, attempt.id)
    _free_lock_file(tmp_path, "another-attempt")
    capsys.readouterr()

    result = _requeue(monkeypatch, tmp_path, task)

    output = capsys.readouterr().out
    attempts = _attempts(tmp_path, task.id)

    assert result == 0
    assert _status(tmp_path, task.id) == "ready"
    assert [a.ended_as for a in attempts] == ["requeued"]
    assert attempts[0].reason == "looks stuck"
    assert "Previous status: running" in output
    assert (
        "Note: the aic process that ran it has ended, and its child may "
        "still be running."
    ) in output
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        "another-attempt" + RUN_LOCK_SUFFIX,
    ]


def test_a_run_with_no_lock_file_is_requeued_with_no_note(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task, attempt = _running_task(tmp_path, monkeypatch)
    capsys.readouterr()

    result = _requeue(monkeypatch, tmp_path, task)

    output = capsys.readouterr().out

    assert result == 0
    assert _status(tmp_path, task.id) == "ready"
    assert "Note:" not in output
    assert not os.path.lexists(tmp_path / RUNS_DIR_NAME)


def test_a_requeue_with_no_open_attempt_still_works(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task, attempt = _running_task(tmp_path, monkeypatch)
    ExecutionRecordRegistry.beside(tmp_path / "tasks.json").close_attempt(
        task.id,
        "failed",
        "closed by hand",
    )
    _free_lock_file(tmp_path, attempt.id)
    capsys.readouterr()

    result = _requeue(monkeypatch, tmp_path, task)

    assert result == 0
    assert "Note:" not in capsys.readouterr().out
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        attempt.id + RUN_LOCK_SUFFIX,
    ]


def test_a_lock_file_that_cannot_be_removed_does_not_stop_the_requeue(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task, attempt = _running_task(tmp_path, monkeypatch)
    _free_lock_file(tmp_path, attempt.id)
    capsys.readouterr()

    def refuse(path):
        raise PermissionError("in use")

    monkeypatch.setattr(run_lock.os, "remove", refuse)

    result = _requeue(monkeypatch, tmp_path, task)

    assert result == 0
    assert _status(tmp_path, task.id) == "ready"
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        attempt.id + RUN_LOCK_SUFFIX,
    ]


def test_a_blank_reason_is_refused_before_the_owner_is_asked(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task, attempt = _running_task(tmp_path, monkeypatch)
    _free_lock_file(tmp_path, attempt.id)
    capsys.readouterr()

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "requeue",
        task.id,
        "--reason",
        "  ",
    )

    assert result == 1
    assert "a reason is required" in capsys.readouterr().out
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        attempt.id + RUN_LOCK_SUFFIX,
    ]


def test_a_task_that_is_not_running_is_still_refused_as_before(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    goal = Goal.create(description="Requeue goal", project="TestProject")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Ready task")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    assert _requeue(monkeypatch, tmp_path, task) == 1
    assert "only a running task can be requeued" in capsys.readouterr().out


def test_a_run_that_aic_task_run_is_making_cannot_be_requeued(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    goal = Goal.create(description="Requeue goal", project="TestProject")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Run task")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")
    answers = []

    class Operator:
        requires_grant = False

        def execute(self, request):
            answers.append(_requeue(monkeypatch, tmp_path, task))
            answers.append(capsys.readouterr().out)

            return ExecutionOutcome(
                task_id=request.task_id,
                outcome="completed",
                reason="scripted completed",
            )

    adapters = ExecutionAdapterRegistry()
    adapters.register("scripted", Operator())
    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.build_adapter_registry",
        lambda: adapters,
    )

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        task.id,
        "--target",
        "scripted",
    )

    assert result == 0
    assert answers[0] == 1
    assert "is still alive" in answers[1]
    assert _status(tmp_path, task.id) == "completed"
    assert [a.ended_as for a in _attempts(tmp_path, task.id)] == [
        "completed",
    ]
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []


def test_other_commands_still_work_while_a_run_holds_its_lock(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task, attempt = _running_task(tmp_path, monkeypatch)
    capsys.readouterr()

    with hold_run_lock(tmp_path, attempt.id):
        assert run_cli(monkeypatch, tmp_path, "task", "running") == 0
        assert run_cli(monkeypatch, tmp_path, "task", "status", task.id) == 0
        assert run_cli(monkeypatch, tmp_path, "task", "history", task.id) == 0

    assert "Owner: alive" in capsys.readouterr().out


def test_the_requeue_still_takes_the_state_lock(
    tmp_path,
    monkeypatch,
    capsys,
    start_lock_holder,
) -> None:
    task, attempt = _running_task(tmp_path, monkeypatch)
    _free_lock_file(tmp_path, attempt.id)
    start_lock_holder(tmp_path)
    monkeypatch.setattr(locking, "DEFAULT_LOCK_TIMEOUT", 0.3)
    capsys.readouterr()

    result = _requeue(monkeypatch, tmp_path, task)

    assert result == 1
    assert _status(tmp_path, task.id) == "running"
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == [
        attempt.id + RUN_LOCK_SUFFIX,
    ]


def test_the_running_listing_says_that_a_live_owner_is_refused(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _running_task(tmp_path, monkeypatch)
    capsys.readouterr()

    run_cli(monkeypatch, tmp_path, "task", "running")

    output = capsys.readouterr().out

    assert (
        "A task listed here may still be running. "
        "Requeueing a live run runs the task twice."
    ) in output
    assert (
        "aic task requeue refuses a run whose owner is alive."
    ) in output
    assert "dead" not in output
    assert "stale" not in output


def _first_line(process, seconds):
    lines = []

    def read():
        lines.append(process.stdout.readline().strip())

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(seconds)

    return lines[0] if lines else ""


def test_a_real_owner_blocks_the_requeue_until_it_is_killed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    task, attempt = _running_task(tmp_path, monkeypatch)
    capsys.readouterr()

    owner = subprocess.Popen(
        [sys.executable, "-B", "-c", _HOLDER, str(tmp_path), attempt.id],
        stdout=subprocess.PIPE,
        text=True,
    )

    try:
        assert _first_line(owner, 60) == "held"

        refused = _requeue(monkeypatch, tmp_path, task)
        status_while_alive = _status(tmp_path, task.id)

        owner.kill()
        owner.wait(timeout=30)

        allowed = _requeue(monkeypatch, tmp_path, task)
    finally:
        owner.kill()
        owner.wait(timeout=30)
        owner.stdout.close()

    output = capsys.readouterr().out

    assert refused == 1
    assert status_while_alive == "running"
    assert allowed == 0
    assert _status(tmp_path, task.id) == "ready"
    assert "its child may still be running" in output
    assert os.listdir(tmp_path / RUNS_DIR_NAME) == []
