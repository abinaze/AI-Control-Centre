"""Tests for what aic goal archive says about attempts left open."""

import json
import os
import re
import sys

from aic_control_centre.cli import main
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.storage import StateFileError

HINT = 'Close each with: aic task close-attempt <task-id> --reason "<text>"'


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _id(output):
    return re.search(r"^ID: (\S+)", output, re.M).group(1)


def _failing_close(self, *args, **kwargs):
    raise StateFileError("executions.json cannot be written: simulated")


def _goal_with_tasks(tmp_path, monkeypatch, capsys, count, stuck):
    """Make a goal with count started tasks, and finish some of them.

    The first `stuck` tasks are finished while the close of their attempt
    fails, which is the state of G11. The failing write is simulated.
    """
    data = tmp_path / "data"
    project = tmp_path / "project"
    data.mkdir()
    project.mkdir()

    assert run_cli(monkeypatch, data, "project", "add", str(project)) == 0
    assert run_cli(
        monkeypatch, data, "goal", "create", "--project", project.name, "g",
    ) == 0
    goal = _id(capsys.readouterr().out)
    tasks = []

    for number in range(count):
        assert run_cli(
            monkeypatch, data, "task", "create", "--goal", goal,
            f"task {number}",
        ) == 0
        task = _id(capsys.readouterr().out)
        tasks.append(task)
        assert run_cli(monkeypatch, data, "task", "ready", task) == 0
        assert run_cli(monkeypatch, data, "task", "start", task) == 0
        capsys.readouterr()

    for task in tasks[:stuck]:
        with monkeypatch.context() as patched:
            patched.setattr(
                ExecutionRecordRegistry,
                "close_attempt",
                _failing_close,
            )

            assert run_cli(
                patched, data, "task", "complete", task, "--reason", "done",
            ) == 1

    capsys.readouterr()

    return data, goal, tasks


def _archive(monkeypatch, data, goal):
    return run_cli(
        monkeypatch, data, "goal", "archive", "--reason", "done", goal,
    )


def _first_record(data, task):
    records = ExecutionRecordRegistry.beside(data / "tasks.json")

    return records.list_attempts(task)[0].id


def test_the_refusal_lists_the_task_and_the_command(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, tasks = _goal_with_tasks(tmp_path, monkeypatch, capsys, 1, 1)
    record = _first_record(data, tasks[0])

    assert _archive(monkeypatch, data, goal) == 1

    assert capsys.readouterr().out.splitlines() == [
        f"Error: goal {goal} cannot be archived: execution record {record} "
        "is still open",
        "Tasks with an attempt that was left open: 1",
        f"- {tasks[0]}",
        HINT,
        "Nothing was changed.",
    ]
    assert not os.path.lexists(data / "archive.json")


def test_every_task_with_an_open_attempt_is_listed_in_order(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, tasks = _goal_with_tasks(tmp_path, monkeypatch, capsys, 3, 3)

    assert _archive(monkeypatch, data, goal) == 1

    lines = capsys.readouterr().out.splitlines()

    assert lines[1:5] == [
        "Tasks with an attempt that was left open: 3",
        f"- {tasks[0]}",
        f"- {tasks[1]}",
        f"- {tasks[2]}",
    ]


def test_a_long_list_is_cut_and_says_how_many_more(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, tasks = _goal_with_tasks(tmp_path, monkeypatch, capsys, 3, 3)
    monkeypatch.setattr(
        "aic_control_centre.goals.commands.MAX_UNFINISHED_SHOWN",
        1,
    )

    assert _archive(monkeypatch, data, goal) == 1

    lines = capsys.readouterr().out.splitlines()

    assert lines[1:5] == [
        "Tasks with an attempt that was left open: 3",
        f"- {tasks[0]}",
        "  and 2 more",
        HINT,
    ]


def test_unfinished_tasks_are_listed_and_the_open_attempts_are_not(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, tasks = _goal_with_tasks(tmp_path, monkeypatch, capsys, 2, 1)

    assert _archive(monkeypatch, data, goal) == 1

    output = capsys.readouterr().out

    assert "Tasks that are not finished: 1" in output
    assert f"- {tasks[1]} (running)" in output
    assert "left open" not in output
    assert "close-attempt" not in output


def test_a_goal_without_a_stuck_attempt_is_archived_as_before(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, tasks = _goal_with_tasks(tmp_path, monkeypatch, capsys, 1, 0)

    assert run_cli(
        monkeypatch, data, "task", "complete", tasks[0], "--reason", "ok",
    ) == 0
    capsys.readouterr()

    assert _archive(monkeypatch, data, goal) == 0

    output = capsys.readouterr().out

    assert output.startswith(f"Goal archived: {goal}")
    assert "close-attempt" not in output


def test_the_goal_is_archived_after_each_attempt_is_closed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, tasks = _goal_with_tasks(tmp_path, monkeypatch, capsys, 2, 2)

    for task in tasks:
        assert run_cli(
            monkeypatch, data, "task", "close-attempt", task,
            "--reason", "the write failed",
        ) == 0

    capsys.readouterr()

    assert _archive(monkeypatch, data, goal) == 0


def test_a_task_with_two_open_records_is_listed_once(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    data, goal, tasks = _goal_with_tasks(tmp_path, monkeypatch, capsys, 2, 2)
    path = data / "executions.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    key = [name for name, value in stored.items() if isinstance(value, list)]
    records = stored[key[0]]
    extra = dict(records[0])
    extra["id"] = "a-second-open-record"
    records.append(extra)
    path.write_text(json.dumps(stored), encoding="utf-8")

    assert _archive(monkeypatch, data, goal) == 1

    lines = capsys.readouterr().out.splitlines()

    assert lines[1:4] == [
        "Tasks with an attempt that was left open: 2",
        f"- {tasks[0]}",
        f"- {tasks[1]}",
    ]
    assert lines[4] == HINT
