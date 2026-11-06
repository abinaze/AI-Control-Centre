"""Tests for aic task create with a goal whose archive was interrupted."""

import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from aic_control_centre.cli import main
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.goals.archive import GoalArchive
from aic_control_centre.goals.archiving import GoalArchiver
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _world(tmp_path):
    """Real registries in one data directory, and an archiver over them."""
    goals = GoalRegistry(tmp_path / "goals.json")
    tasks = TaskRegistry(tmp_path / "tasks.json")
    records = ExecutionRecordRegistry.beside(tasks.registry_path)
    archive = GoalArchive.beside(tasks.registry_path)

    return SimpleNamespace(
        goals=goals,
        tasks=tasks,
        records=records,
        archive=archive,
        archiver=GoalArchiver(goals, tasks, records, archive, None),
    )


def _goal(world, statuses=(), goal_status="pending", project="app"):
    """Add a goal with one task for each status, and the goal's status."""
    created = Goal.create(f"Work on {project}", project)
    goal = replace(created, status=goal_status)
    world.goals.add_goal(goal)

    for number, status in enumerate(statuses):
        task = replace(Task.create(goal.id, f"task {number}"), status=status)
        world.tasks.add_task(task)

    return goal


STEPS = ["records", "tasks", "goal"]


def _interrupt(world, monkeypatch, goal, step="goal"):
    """Archive a goal and make one of the removals fail, as a crash would."""
    targets = {
        "records": (world.records, "remove_records"),
        "tasks": (world.tasks, "remove_tasks"),
        "goal": (world.goals, "remove_goal"),
    }
    owner, name = targets[step]

    def boom(*arguments, **options):
        raise OSError("crash")

    with monkeypatch.context() as patch:
        patch.setattr(owner, name, boom)

        with pytest.raises(OSError):
            world.archiver.archive_goal(goal.id, "tidy up")

    assert world.archive.get_entry(goal.id) is not None
    assert goal in world.goals.list_goals()


def _create(monkeypatch, tmp_path, goal):
    return run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "create",
        "--goal",
        goal.id,
        "late task",
    )


def _refusal(goal):
    return (
        f"Error: goal {goal.id} is already archived, and the archive was "
        "not finished; finish it with: "
        f"aic goal archive {goal.id} --reason <text>\n"
    )


@pytest.mark.parametrize("step", STEPS)
def test_a_goal_that_had_no_tasks_gets_none_after_an_interrupted_archive(
    tmp_path,
    monkeypatch,
    capsys,
    step,
) -> None:
    """The window that G21 describes is closed for a goal with no tasks."""
    world = _world(tmp_path)
    goal = _goal(world)
    _interrupt(world, monkeypatch, goal, step)
    capsys.readouterr()

    assert _create(monkeypatch, tmp_path, goal) == 1
    assert capsys.readouterr().out == _refusal(goal)
    assert world.tasks.list_tasks() == []
    assert not (tmp_path / "tasks.json").exists()


@pytest.mark.parametrize("step", STEPS)
@pytest.mark.parametrize("status", ["completed", "failed"])
def test_a_goal_that_had_finished_tasks_gets_the_archive_message(
    tmp_path,
    monkeypatch,
    capsys,
    status,
    step,
) -> None:
    """The message says how to finish, not that the goal is closed.

    A crash at an earlier step leaves the tasks in the active file, and a
    crash at the last one has removed them, and both are refused alike.
    """
    world = _world(tmp_path)
    goal = _goal(world, (status,), goal_status=status)
    _interrupt(world, monkeypatch, goal, step)
    capsys.readouterr()
    before = world.tasks.list_tasks()

    assert _create(monkeypatch, tmp_path, goal) == 1

    output = capsys.readouterr().out

    assert output == _refusal(goal)
    assert "Cannot create task" not in output
    assert world.tasks.list_tasks() == before
    assert len(before) == (0 if step == "goal" else 1)


def test_a_goal_that_has_no_entry_still_gets_a_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """With no archive file at all, a task is created as before."""
    world = _world(tmp_path)
    goal = _goal(world)

    assert not (tmp_path / "archive.json").exists()
    assert _create(monkeypatch, tmp_path, goal) == 0
    assert "Task created." in capsys.readouterr().out
    assert [t.goal_id for t in world.tasks.list_tasks()] == [goal.id]


def test_other_goals_in_the_archive_do_not_block_a_goal(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """One goal that is archived, and one that is interrupted, are others."""
    world = _world(tmp_path)
    done = _goal(world, ("completed",), goal_status="completed")
    stuck = _goal(world)
    mine = _goal(world)
    world.archiver.archive_goal(done.id, "done")
    _interrupt(world, monkeypatch, stuck)
    capsys.readouterr()

    assert _create(monkeypatch, tmp_path, mine) == 0
    assert "Task created." in capsys.readouterr().out
    assert [t.goal_id for t in world.tasks.list_tasks()] == [mine.id]


@pytest.mark.parametrize("statuses", [(), ("completed",)])
def test_the_interrupted_archive_can_still_be_finished(
    tmp_path,
    monkeypatch,
    capsys,
    statuses,
) -> None:
    """After the refusal, archiving again ends it and the state is valid."""
    world = _world(tmp_path)
    goal_status = "completed" if statuses else "pending"
    goal = _goal(world, statuses, goal_status=goal_status)
    _interrupt(world, monkeypatch, goal)

    assert _create(monkeypatch, tmp_path, goal) == 1

    code = run_cli(
        monkeypatch,
        tmp_path,
        "goal",
        "archive",
        goal.id,
        "--reason",
        "again",
    )
    output = capsys.readouterr().out

    assert code == 0
    assert f"Goal archive finished: {goal.id}" in output
    assert "its reason is kept" in output
    assert world.goals.list_goals() == []
    assert world.archive.get_entry(goal.id).reason == "tidy up"
    assert run_cli(monkeypatch, tmp_path, "validate") == 0
    assert "Validation passed." in capsys.readouterr().out


def test_an_archive_that_cannot_be_read_creates_no_task(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The error is the one that other commands print, and nothing is made."""
    world = _world(tmp_path)
    goal = _goal(world)
    (tmp_path / "archive.json").write_text("not json", encoding="utf-8")

    assert _create(monkeypatch, tmp_path, goal) == 1

    output = capsys.readouterr().out

    assert output.startswith("Error: ")
    assert "archive.json" in output
    assert world.tasks.list_tasks() == []


def test_a_goal_that_does_not_exist_is_still_not_found(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The goal is looked up first, so the old message is unchanged."""
    world = _world(tmp_path)
    ghost = Goal.create("Never added", "app")

    assert _create(monkeypatch, tmp_path, ghost) == 1
    assert capsys.readouterr().out == f"Error: goal not found: {ghost.id}\n"
    assert world.tasks.list_tasks() == []


def test_the_message_names_the_goal_that_was_found(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """An id that was typed with spaces is shown as the goal's own id."""
    world = _world(tmp_path)
    goal = _goal(world)
    _interrupt(world, monkeypatch, goal)
    capsys.readouterr()

    code = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "create",
        "--goal",
        f"  {goal.id}  ",
        "late task",
    )

    assert code == 1
    assert capsys.readouterr().out == _refusal(goal)
