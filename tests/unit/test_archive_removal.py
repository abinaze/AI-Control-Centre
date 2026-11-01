"""Tests for taking goals, tasks and records out of the active files."""

from dataclasses import replace

import pytest

from aic_control_centre.execution import records as records_module
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.goals import registry as goals_module
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.tasks import registry as tasks_module
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


def _goals(tmp_path, count=3):
    registry = GoalRegistry(tmp_path / "goals.json")
    goals = [Goal.create(f"goal {number}", "app") for number in range(count)]

    for goal in goals:
        registry.add_goal(goal)

    return registry, goals


def _tasks(tmp_path, count=4):
    registry = TaskRegistry(tmp_path / "tasks.json")
    tasks = [
        replace(Task.create("goal", f"task {number}"), status="completed")
        for number in range(count)
    ]

    for task in tasks:
        registry.add_task(task)

    return registry, tasks


def _records(tmp_path, count=4):
    registry = ExecutionRecordRegistry(tmp_path / "executions.json")
    records = []

    for number in range(count):
        task_id = f"task-{number}"
        registry.open_attempt(task_id, "coordinator", "noop")
        records.append(
            registry.close_attempt(task_id, "completed", "ok", "coordinator"),
        )

    return registry, records


def test_a_goal_is_removed_and_the_others_stay(tmp_path) -> None:
    """Only the goal that was named goes, and the order is kept."""
    registry, goals = _goals(tmp_path)

    assert registry.remove_goal(goals[1].id) is True

    assert registry.list_goals() == [goals[0], goals[2]]
    assert GoalRegistry(registry.registry_path).list_goals() == [
        goals[0],
        goals[2],
    ]


def test_removing_a_goal_that_is_not_there_writes_nothing(tmp_path) -> None:
    """The answer is False and the file is the same bytes."""
    registry, _ = _goals(tmp_path)
    before = registry.registry_path.read_bytes()

    assert registry.remove_goal("not-a-goal") is False
    assert registry.registry_path.read_bytes() == before


def test_removing_from_a_goal_file_that_is_not_there_creates_nothing(
    tmp_path,
) -> None:
    """There is nothing to remove, so no file appears."""
    registry = GoalRegistry(tmp_path / "goals.json")

    assert registry.remove_goal("x") is False
    assert not (tmp_path / "goals.json").exists()


def test_tasks_are_removed_and_the_others_stay(tmp_path) -> None:
    """The count is how many went, and the order is kept."""
    registry, tasks = _tasks(tmp_path)

    removed = registry.remove_tasks([tasks[0].id, tasks[2].id, "unknown"])

    assert removed == 2
    assert registry.list_tasks() == [tasks[1], tasks[3]]


def test_removing_no_tasks_writes_nothing(tmp_path) -> None:
    """Neither an empty list nor unknown ids change the file."""
    registry, _ = _tasks(tmp_path)
    before = registry.registry_path.read_bytes()

    assert registry.remove_tasks([]) == 0
    assert registry.remove_tasks({"unknown"}) == 0
    assert registry.registry_path.read_bytes() == before


def test_records_are_removed_and_the_others_stay(tmp_path) -> None:
    """The count is how many went, and the order is kept."""
    registry, records = _records(tmp_path)

    removed = registry.remove_records(
        [records[1].id, records[3].id, "unknown"],
    )

    assert removed == 2
    assert registry.list_records() == [records[0], records[2]]


def test_removing_no_records_writes_nothing(tmp_path) -> None:
    """Neither an empty list nor unknown ids change the file."""
    registry, _ = _records(tmp_path)
    before = registry.registry_path.read_bytes()

    assert registry.remove_records(iter([])) == 0
    assert registry.remove_records({"unknown"}) == 0
    assert registry.registry_path.read_bytes() == before


def test_a_failed_write_keeps_each_file_as_it_was(
    tmp_path,
    monkeypatch,
) -> None:
    """The error is raised, and what was in the file is still there."""
    goals, goal_list = _goals(tmp_path)
    tasks, task_list = _tasks(tmp_path)
    records, record_list = _records(tmp_path)
    before = [
        registry.registry_path.read_bytes()
        for registry in (goals, tasks, records)
    ]

    def refuse(path, text):
        raise OSError("disk full")

    for module in (goals_module, tasks_module, records_module):
        monkeypatch.setattr(module, "write_text_atomic", refuse)

    with pytest.raises(OSError):
        goals.remove_goal(goal_list[0].id)

    with pytest.raises(OSError):
        tasks.remove_tasks([task_list[0].id])

    with pytest.raises(OSError):
        records.remove_records([record_list[0].id])

    monkeypatch.undo()

    assert [
        registry.registry_path.read_bytes()
        for registry in (goals, tasks, records)
    ] == before


def test_removing_from_a_task_file_that_is_not_there_creates_nothing(
    tmp_path,
) -> None:
    """There is nothing to remove, so no file appears."""
    registry = TaskRegistry(tmp_path / "tasks.json")

    assert registry.remove_tasks(["x"]) == 0
    assert not (tmp_path / "tasks.json").exists()


def test_removing_from_a_record_file_that_is_not_there_creates_nothing(
    tmp_path,
) -> None:
    """There is nothing to remove, so no file appears."""
    registry = ExecutionRecordRegistry(tmp_path / "executions.json")

    assert registry.remove_records(["x"]) == 0
    assert not (tmp_path / "executions.json").exists()
