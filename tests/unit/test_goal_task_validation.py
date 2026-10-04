"""Tests for goal and task state validation."""

from aic_control_centre.goals.model import (
    GOAL_STATUS_COMPLETED,
    GOAL_STATUS_FAILED,
    GOAL_STATUS_IN_PROGRESS,
    Goal,
)
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import (
    TASK_STATUS_COMPLETED,
    Task,
)
from aic_control_centre.tasks.registry import TaskRegistry
from aic_control_centre.validation.goal_tasks import (
    GoalTaskValidator,
    validate_task_creation,
)


def test_empty_state_is_valid(tmp_path) -> None:
    """An empty goal/task registry is valid."""
    validator = GoalTaskValidator(
        goal_registry=GoalRegistry(tmp_path / "goals.json"),
        task_registry=TaskRegistry(tmp_path / "tasks.json"),
    )

    result = validator.validate()

    assert result.valid is True
    assert result.errors == ()


def test_goal_with_pending_task_requires_in_progress_status(tmp_path) -> None:
    """A consistent goal and task graph passes validation."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Build validation",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task_registry.add_task(
        Task.create(
            goal_id=goal.id,
            title="Implement validation",
        )
    )

    result = GoalTaskValidator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    ).validate()

    assert result.valid is False
    assert (
        f"Goal {goal.id} status mismatch: "
        "persisted=pending, derived=in_progress"
    ) in result.errors


def test_orphan_task_is_detected(tmp_path) -> None:
    """A task referencing a missing goal is invalid."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    task = Task.create(
        goal_id="missing-goal",
        title="Orphan task",
    )
    task_registry.add_task(task)

    result = GoalTaskValidator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    ).validate()

    assert result.valid is False
    assert (
        f"Task {task.id} references missing goal: missing-goal"
    ) in result.errors


def test_unknown_goal_status_is_detected(tmp_path) -> None:
    """An unknown persisted goal status is invalid."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")

    goal = Goal.create(
        description="Invalid goal",
        project="TestProject",
    )
    invalid_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status="corrupted",
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )
    goal_registry.add_goal(invalid_goal)

    result = GoalTaskValidator(
        goal_registry=goal_registry,
        task_registry=TaskRegistry(tmp_path / "tasks.json"),
    ).validate()

    assert result.valid is False
    assert (
        f"Goal {goal.id} has unknown status: corrupted"
    ) in result.errors


def test_unknown_task_status_is_detected(tmp_path) -> None:
    """An unknown persisted task status is invalid."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Invalid task",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Invalid task",
    )
    invalid_task = Task(
        id=task.id,
        goal_id=task.goal_id,
        title=task.title,
        description=task.description,
        status="corrupted",
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
    task_registry.add_task(invalid_task)

    result = GoalTaskValidator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    ).validate()

    assert result.valid is False
    assert (
        f"Task {task.id} has unknown status: corrupted"
    ) in result.errors


def test_completed_goal_with_completed_tasks_is_valid(tmp_path) -> None:
    """A completed goal is valid when every task is completed."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Completed goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Completed task",
    )
    completed = Task(
        id=task.id,
        goal_id=task.goal_id,
        title=task.title,
        description=task.description,
        status=TASK_STATUS_COMPLETED,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
    task_registry.add_task(completed)

    completed_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status=GOAL_STATUS_COMPLETED,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )
    goal_registry.update_goal(completed_goal)

    result = GoalTaskValidator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    ).validate()

    assert result.valid is True
    assert result.errors == ()


def test_failed_goal_with_failed_task_is_valid(tmp_path) -> None:
    """A failed goal is valid when at least one task has failed."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    task_registry = TaskRegistry(tmp_path / "tasks.json")

    goal = Goal.create(
        description="Failed goal",
        project="TestProject",
    )
    goal_registry.add_goal(goal)

    task = Task.create(
        goal_id=goal.id,
        title="Failed task",
    )
    failed = Task(
        id=task.id,
        goal_id=task.goal_id,
        title=task.title,
        description=task.description,
        status="failed",
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
    task_registry.add_task(failed)

    failed_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status=GOAL_STATUS_FAILED,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )
    goal_registry.update_goal(failed_goal)

    result = GoalTaskValidator(
        goal_registry=goal_registry,
        task_registry=task_registry,
    ).validate()

    assert result.valid is True
    assert result.errors == ()


def test_completed_goal_cannot_receive_new_task() -> None:
    """Completed goals cannot receive new tasks."""
    goal = Goal.create(
        description="Completed goal",
        project="TestProject",
    )
    completed_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status=GOAL_STATUS_COMPLETED,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )

    assert (
        validate_task_creation(completed_goal)
        == f"Cannot create task for completed goal: {goal.id}"
    )


def test_failed_goal_cannot_receive_new_task() -> None:
    """Failed goals cannot receive new tasks."""
    goal = Goal.create(
        description="Failed goal",
        project="TestProject",
    )
    failed_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status=GOAL_STATUS_FAILED,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )

    assert (
        validate_task_creation(failed_goal)
        == f"Cannot create task for failed goal: {goal.id}"
    )


def test_unknown_goal_status_cannot_receive_new_task() -> None:
    """Goals with invalid statuses cannot receive tasks."""
    goal = Goal.create(
        description="Invalid goal",
        project="TestProject",
    )
    invalid_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status="corrupted",
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )

    assert (
        validate_task_creation(invalid_goal)
        == f"Goal {goal.id} has unknown status: corrupted"
    )


def test_in_progress_goal_can_receive_new_task() -> None:
    """An active goal may receive another task."""
    goal = Goal.create(
        description="Active goal",
        project="TestProject",
    )
    active_goal = Goal(
        id=goal.id,
        description=goal.description,
        project=goal.project,
        status=GOAL_STATUS_IN_PROGRESS,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )

    assert validate_task_creation(active_goal) is None


def _validator_with_projects(tmp_path, project_names):
    """Build a validator whose project registry holds the given names."""
    project_registry = ProjectRegistry(tmp_path / "projects.json")

    for name in project_names:
        project_path = tmp_path / name
        project_path.mkdir()
        project_registry.add_project(project_path)

    return GoalTaskValidator(
        goal_registry=GoalRegistry(tmp_path / "goals.json"),
        task_registry=TaskRegistry(tmp_path / "tasks.json"),
        project_registry=project_registry,
    )


def test_project_references_are_not_checked_without_a_registry(
    tmp_path,
) -> None:
    """Without a project registry, project names are not validated."""
    goal_registry = GoalRegistry(tmp_path / "goals.json")
    goal_registry.add_goal(
        Goal.create(description="Unchecked goal", project="Unregistered"),
    )
    validator = GoalTaskValidator(
        goal_registry=goal_registry,
        task_registry=TaskRegistry(tmp_path / "tasks.json"),
    )

    assert validator.validate().valid is True


def test_goal_for_registered_project_is_valid(tmp_path) -> None:
    """A goal whose project is registered passes validation."""
    validator = _validator_with_projects(tmp_path, ["Aircursor"])
    validator.goal_registry.add_goal(
        Goal.create(description="Registered goal", project="Aircursor"),
    )

    result = validator.validate()

    assert result.valid is True
    assert result.errors == ()


def test_goal_for_unregistered_project_is_reported(tmp_path) -> None:
    """A goal pointing at an unregistered project is a validation error."""
    validator = _validator_with_projects(tmp_path, ["Aircursor"])
    goal = Goal.create(description="Orphan goal", project="Ghost")
    validator.goal_registry.add_goal(goal)

    result = validator.validate()

    assert result.valid is False
    assert result.errors == (
        f"Goal {goal.id} references unregistered project: Ghost",
    )


def test_every_goal_with_an_unregistered_project_is_reported(
    tmp_path,
) -> None:
    """Each goal with an unregistered project gets its own error."""
    validator = _validator_with_projects(tmp_path, ["Aircursor"])
    first = Goal.create(description="First orphan", project="Ghost")
    second = Goal.create(description="Second orphan", project="Phantom")
    valid = Goal.create(description="Fine goal", project="Aircursor")

    for goal in (first, valid, second):
        validator.goal_registry.add_goal(goal)

    result = validator.validate()

    assert result.errors == (
        f"Goal {first.id} references unregistered project: Ghost",
        f"Goal {second.id} references unregistered project: Phantom",
    )
