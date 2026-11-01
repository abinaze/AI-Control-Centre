"""Tests for aic validate and the archive of goals."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.goals.archive import (
    ArchiveEntry,
    GoalArchive,
    _entry_to_item,
)
from aic_control_centre.goals.archiving import GoalArchiver
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.storage import (
    StateFileError,
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.validation.goal_tasks import GoalTaskValidator


def _world(tmp_path):
    goals = GoalRegistry(tmp_path / "goals.json")
    tasks = TaskRegistry(tmp_path / "tasks.json")
    records = ExecutionRecordRegistry.beside(tasks.registry_path)
    archive = GoalArchive.beside(tasks.registry_path)

    return SimpleNamespace(
        goals=goals,
        tasks=tasks,
        records=records,
        archive=archive,
        archiver=GoalArchiver(goals, tasks, records, archive),
        path=tmp_path,
    )


def _goal(world):
    goal = replace(Goal.create("Ship it", "app"), status="completed")
    world.goals.add_goal(goal)
    task = replace(Task.create(goal.id, "only"), status="completed")
    world.tasks.add_task(task)
    world.records.open_attempt(task.id, "coordinator", "noop")
    world.records.close_attempt(task.id, "completed", "ok", "coordinator")

    return goal


def _validator(world, with_archive=True):
    return GoalTaskValidator(
        goal_registry=world.goals,
        task_registry=world.tasks,
        record_registry=world.records,
        archive_registry=world.archive if with_archive else None,
    )


def _entry(world, goal):
    return ArchiveEntry.create(
        goal,
        world.tasks.list_tasks_for_goal(goal.id),
        world.records.list_records(),
        "tidy up",
    )


def test_a_state_with_no_archive_is_valid(tmp_path) -> None:
    """An archive file that is not there is not an error."""
    world = _world(tmp_path)
    _goal(world)

    assert _validator(world).validate().valid is True


def test_a_finished_archive_is_valid(tmp_path) -> None:
    """Nothing is left that names the archived goal."""
    world = _world(tmp_path)
    goal = _goal(world)
    world.archiver.archive_goal(goal.id, "done")

    result = _validator(world).validate()

    assert result.valid is True
    assert world.archive.has_goal(goal.id) is True


def test_a_goal_that_is_archived_and_active_is_reported(tmp_path) -> None:
    """The message says what to run."""
    world = _world(tmp_path)
    goal = _goal(world)
    world.archive.add_entry(_entry(world, goal))

    errors = _validator(world).validate().errors

    assert errors == (
        f"Goal {goal.id} is archived and also still active; "
        f"finish it with: aic goal archive {goal.id} --reason <text>",
    )


def test_the_archive_is_not_checked_without_an_archive_registry(
    tmp_path,
) -> None:
    """Like the other optional registries, it is checked only if given."""
    world = _world(tmp_path)
    goal = _goal(world)
    world.archive.add_entry(_entry(world, goal))

    assert _validator(world, with_archive=False).validate().valid is True


def test_a_goal_archived_twice_is_reported(tmp_path) -> None:
    """A file that was edited by hand can hold an entry twice."""
    world = _world(tmp_path)
    goal = _goal(world)
    item = _entry_to_item(_entry(world, goal))
    world.archiver.archive_goal(goal.id, "done")
    write_text_atomic(
        world.archive.registry_path,
        serialize_state_items("archived", [item, item]),
    )

    assert _validator(world).validate().errors == (
        f"Goal {goal.id} is archived more than once",
    )


@pytest.mark.parametrize("step", ["records", "tasks", "goal"])
def test_a_crash_is_reported_and_archiving_again_clears_it(
    tmp_path,
    monkeypatch,
    step,
) -> None:
    """The state after a crash fails validation, and the repair passes it."""
    world = _world(tmp_path)
    goal = _goal(world)
    owner, name = {
        "records": (world.records, "remove_records"),
        "tasks": (world.tasks, "remove_tasks"),
        "goal": (world.goals, "remove_goal"),
    }[step]

    def boom(*arguments, **options):
        raise OSError("crash")

    with monkeypatch.context() as patch:
        patch.setattr(owner, name, boom)

        with pytest.raises(OSError):
            world.archiver.archive_goal(goal.id, "tidy up")

    errors = _validator(world).validate().errors

    assert any("archived and also still active" in e for e in errors)

    world.archiver.archive_goal(goal.id, "tidy up")

    assert _validator(world).validate().valid is True


def test_an_archive_that_cannot_be_read_is_an_error(tmp_path) -> None:
    """It is not read as empty, so validation says so."""
    world = _world(tmp_path)
    _goal(world)
    world.archive.registry_path.write_bytes(b"{ not json")

    with pytest.raises(StateFileError, match="is not valid JSON"):
        _validator(world).validate()
