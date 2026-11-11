"""Tests for archiving a finished goal."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.goals.archive import GoalArchive
from aic_control_centre.goals.archiving import GoalArchiveError, GoalArchiver
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.storage import (
    serialize_state_items,
    write_text_atomic,
)
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry

FINISHED = ("completed", "failed")


def _world(tmp_path):
    """Real registries in one data directory, and an archiver over them."""
    goals = GoalRegistry(tmp_path / "goals.json")
    tasks = TaskRegistry(tmp_path / "tasks.json")
    records = ExecutionRecordRegistry.beside(tasks.registry_path)
    archive = GoalArchive.beside(tasks.registry_path)
    projects = ProjectRegistry(tmp_path / "projects.json")

    return SimpleNamespace(
        goals=goals,
        tasks=tasks,
        records=records,
        archive=archive,
        projects=projects,
        archiver=GoalArchiver(goals, tasks, records, archive, projects),
        path=tmp_path,
    )


def _goal(world, statuses=FINISHED, project="app", open_record=False):
    """Add a goal with one task for each status, and a record for each."""
    goal = Goal.create(f"Work on {project}", project)
    world.goals.add_goal(goal)
    added = []

    for number, status in enumerate(statuses):
        task = replace(Task.create(goal.id, f"task {number}"), status=status)
        world.tasks.add_task(task)
        added.append(task)

        if status in FINISHED:
            world.records.open_attempt(task.id, "coordinator", "noop")

            if not open_record:
                world.records.close_attempt(
                    task.id,
                    status,
                    "why",
                    "coordinator",
                )

    return goal, added


def _active(world):
    return (
        world.goals.list_goals(),
        world.tasks.list_tasks(),
        world.records.list_records(),
    )


def _register(world, name="app"):
    directory = world.path / "work" / name
    directory.mkdir(parents=True)

    return world.projects.add_project(directory)


def test_a_finished_goal_moves_to_the_archive(tmp_path) -> None:
    """The goal, its tasks and its records leave the active files."""
    world = _world(tmp_path)
    project = _register(world)
    goal, tasks = _goal(world)
    records = world.records.list_records()

    result = world.archiver.archive_goal(goal.id, "  tidy up  ")

    assert _active(world) == ([], [], [])
    assert result.goal_id == goal.id
    assert result.project == "app"
    assert result.project_path == str(project.path)
    assert result.tasks == 2
    assert result.records == 2
    assert result.reason == "tidy up"
    assert result.resumed is False
    assert result.already_done is False

    entry = world.archive.get_entry(goal.id)

    assert entry.goal == goal
    assert entry.tasks == tuple(tasks)
    assert entry.records == tuple(records)
    assert entry.reason == "tidy up"
    assert entry.project_path == str(project.path)


def test_other_goals_are_left_alone(tmp_path) -> None:
    """Their tasks and records stay where they were."""
    world = _world(tmp_path)
    mine, _ = _goal(world)
    other, other_tasks = _goal(world, ("completed",), "lib")
    other_records = [
        record
        for record in world.records.list_records()
        if record.task_id == other_tasks[0].id
    ]

    world.archiver.archive_goal(mine.id, "done")

    goals, tasks, records = _active(world)

    assert goals == [other]
    assert tasks == other_tasks
    assert records == other_records


def test_a_goal_with_no_tasks_is_archived(tmp_path) -> None:
    """There is nothing to move but the goal."""
    world = _world(tmp_path)
    goal, _ = _goal(world, ())

    result = world.archiver.archive_goal(goal.id, "never used")

    assert (result.tasks, result.records) == (0, 0)
    assert _active(world) == ([], [], [])
    assert world.archive.has_goal(goal.id) is True


def test_a_project_that_is_not_registered_has_no_directory(tmp_path) -> None:
    """The entry says so instead of guessing."""
    world = _world(tmp_path)
    goal, _ = _goal(world)

    result = world.archiver.archive_goal(goal.id, "done")

    assert result.project_path is None
    assert world.archive.get_entry(goal.id).project_path is None


def test_a_project_name_with_two_directories_has_no_directory(
    tmp_path,
) -> None:
    """The name does not say which directory was meant."""
    world = _world(tmp_path)
    first = tmp_path / "one" / "app"
    second = tmp_path / "two" / "app"
    write_text_atomic(
        tmp_path / "projects.json",
        serialize_state_items(
            "projects",
            [
                {"name": "app", "path": str(first)},
                {"name": "app", "path": str(second)},
            ],
        ),
    )
    goal, _ = _goal(world)

    assert world.archiver.archive_goal(goal.id, "done").project_path is None


@pytest.mark.parametrize("status", ["pending", "ready", "running"])
def test_a_goal_with_work_in_flight_is_refused(tmp_path, status) -> None:
    """The unfinished tasks are named, and no file changes."""
    world = _world(tmp_path)
    goal, tasks = _goal(world, ("completed", status, "failed"))
    before = [
        path.read_bytes()
        for path in sorted(tmp_path.glob("*.json"))
    ]

    with pytest.raises(GoalArchiveError) as caught:
        world.archiver.archive_goal(goal.id, "done")

    assert str(caught.value) == (
        f"goal {goal.id} has 1 tasks that are not finished"
    )
    assert caught.value.unfinished == (tasks[1],)
    assert [
        path.read_bytes()
        for path in sorted(tmp_path.glob("*.json"))
    ] == before
    assert not (tmp_path / "archive.json").exists()


def test_a_finished_task_with_an_open_record_is_refused(tmp_path) -> None:
    """The record says that an attempt never ended."""
    world = _world(tmp_path)
    goal, _ = _goal(world, ("completed",), open_record=True)

    with pytest.raises(GoalArchiveError, match="cannot be archived"):
        world.archiver.archive_goal(goal.id, "done")

    assert world.goals.get_goal(goal.id) == goal
    assert not (tmp_path / "archive.json").exists()


def test_an_unknown_goal_is_refused(tmp_path) -> None:
    """The error names the id."""
    world = _world(tmp_path)

    with pytest.raises(GoalArchiveError) as caught:
        world.archiver.archive_goal("nope", "done")

    assert str(caught.value) == "goal not found: nope"


@pytest.mark.parametrize("reason", ["", "   ", "\n"])
def test_a_blank_reason_is_refused(tmp_path, reason) -> None:
    """The archive says why, so a reason is needed."""
    world = _world(tmp_path)
    goal, _ = _goal(world)

    with pytest.raises(GoalArchiveError) as caught:
        world.archiver.archive_goal(goal.id, reason)

    assert str(caught.value) == "archive reason cannot be empty"
    assert world.goals.get_goal(goal.id) == goal
    assert not (tmp_path / "archive.json").exists()


def test_a_blank_reason_is_refused_for_an_archived_goal_too(tmp_path) -> None:
    """The command always needs a reason, whatever state the goal is in."""
    world = _world(tmp_path)
    goal, _ = _goal(world)
    world.archiver.archive_goal(goal.id, "first")

    with pytest.raises(GoalArchiveError) as caught:
        world.archiver.archive_goal(goal.id, "  ")

    assert str(caught.value) == "archive reason cannot be empty"


def test_archiving_a_goal_again_does_nothing(tmp_path) -> None:
    """The goal is no longer active, and its entry is the one that is kept."""
    world = _world(tmp_path)
    goal, _ = _goal(world)
    world.archiver.archive_goal(goal.id, "first")
    before = (tmp_path / "archive.json").read_bytes()

    result = world.archiver.archive_goal(goal.id, "second")

    assert result.already_done is True
    assert result.reason == "first"
    assert (tmp_path / "archive.json").read_bytes() == before


def _crash(world, monkeypatch, step):
    """Make one of the four writes fail, as a crash would."""
    targets = {
        "archive": (world.archive, "add_entry"),
        "records": (world.records, "remove_records"),
        "tasks": (world.tasks, "remove_tasks"),
        "goal": (world.goals, "remove_goal"),
    }
    owner, name = targets[step]

    def boom(*arguments, **options):
        raise OSError("crash")

    monkeypatch.setattr(owner, name, boom)


@pytest.mark.parametrize("step", ["archive", "records", "tasks", "goal"])
def test_a_crash_at_any_write_is_finished_by_archiving_again(
    tmp_path,
    monkeypatch,
    step,
) -> None:
    """Every state after a crash is valid, and the same command ends it."""
    world = _world(tmp_path)
    goal, tasks = _goal(world)
    records = world.records.list_records()

    with monkeypatch.context() as patch:
        _crash(world, patch, step)

        with pytest.raises(OSError):
            world.archiver.archive_goal(goal.id, "tidy up")

    archived_before = world.archive.get_entry(goal.id)

    if step == "archive":
        assert archived_before is None
        assert _active(world) == ([goal], tasks, records)
    else:
        assert archived_before is not None
        assert goal in world.goals.list_goals()

    result = world.archiver.archive_goal(goal.id, "a different reason")
    kept = "a different reason" if step == "archive" else "tidy up"

    assert result.resumed is (step != "archive")
    assert result.reason == kept
    assert _active(world) == ([], [], [])
    assert len(world.archive.list_entries()) == 1

    entry = world.archive.get_entry(goal.id)

    assert entry.tasks == tuple(tasks)
    assert entry.records == tuple(records)
    assert entry.reason == kept

    if archived_before is not None:
        assert entry == archived_before


def test_a_task_added_after_a_crash_stops_the_second_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    """The archive does not hold that task, so the goal is not removed."""
    world = _world(tmp_path)
    goal, _ = _goal(world)

    with monkeypatch.context() as patch:
        _crash(world, patch, "records")

        with pytest.raises(OSError):
            world.archiver.archive_goal(goal.id, "tidy up")

    late = Task.create(goal.id, "added later")
    world.tasks.add_task(late)
    before = _active(world)

    with pytest.raises(GoalArchiveError) as caught:
        world.archiver.archive_goal(goal.id, "tidy up")

    assert late.id in str(caught.value)
    assert _active(world) == before
    assert world.goals.get_goal(goal.id) == goal


def test_the_refusal_for_open_records_carries_them(tmp_path) -> None:
    """The command can say which tasks have an attempt that was left open."""
    world = _world(tmp_path)
    goal, tasks = _goal(world, ("completed", "failed"), open_record=True)

    with pytest.raises(GoalArchiveError) as refused:
        world.archiver.archive_goal(goal.id, "done")

    assert {record.task_id for record in refused.value.open_attempts} == {
        task.id for task in tasks
    }
    assert all(record.is_open for record in refused.value.open_attempts)
    assert refused.value.unfinished == ()


def test_the_message_for_an_open_record_names_the_first_one(
    tmp_path,
) -> None:
    """The words of the refusal did not change."""
    world = _world(tmp_path)
    goal, _ = _goal(world, ("completed", "failed"), open_record=True)

    with pytest.raises(GoalArchiveError) as refused:
        world.archiver.archive_goal(goal.id, "done")

    first = refused.value.open_attempts[0]

    assert str(refused.value) == (
        f"goal {goal.id} cannot be archived: "
        f"execution record {first.id} is still open"
    )


def test_unfinished_tasks_are_refused_before_open_records(tmp_path) -> None:
    """The work in flight is what a person has to deal with first."""
    world = _world(tmp_path)
    goal, _ = _goal(world, ("completed", "running"), open_record=True)

    with pytest.raises(GoalArchiveError) as refused:
        world.archiver.archive_goal(goal.id, "done")

    assert len(refused.value.unfinished) == 1
    assert refused.value.open_attempts == ()
