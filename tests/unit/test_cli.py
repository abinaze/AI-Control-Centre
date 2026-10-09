import json
import sys

import pytest

from aic_control_centre.cli import build_parser, main
from aic_control_centre.execution.records import ExecutionRecordRegistry
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


def test_parser_program_name():
    parser = build_parser()

    assert parser.prog == "aic"


def test_parser_description():
    parser = build_parser()

    assert parser.description == (
        "Local-first autonomous AI development and control platform."
    )


def test_version_argument():
    parser = build_parser()

    args = parser.parse_args([])

    assert args is not None


def test_task_lifecycle_commands_are_registered():
    """The task lifecycle commands are available in the CLI parser."""
    parser = build_parser()

    for command in ("ready", "start", "complete", "fail"):
        args = parser.parse_args(
            ["task", command, "task-123"],
        )

        assert args.command == "task"
        assert args.task_command == command
        assert args.task_id == "task-123"


def test_validate_command_is_registered():
    """The validate command is available in the CLI parser."""
    parser = build_parser()

    args = parser.parse_args(["validate"])

    assert args.command == "validate"


def test_task_readiness_command_is_registered():
    """The task readiness command is available in the CLI parser."""
    parser = build_parser()

    args = parser.parse_args(
        ["task", "readiness", "task-123"],
    )

    assert args.command == "task"
    assert args.task_command == "readiness"
    assert args.task_id == "task-123"


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def test_main_reports_newer_schema_version_without_a_traceback(
    tmp_path,
    monkeypatch,
    capsys,
):
    goals_file = tmp_path / "goals.json"
    text = json.dumps({"schema_version": 99, "goals": []})
    goals_file.write_text(text, encoding="utf-8")

    assert run_cli(monkeypatch, tmp_path, "goal", "list") == 1

    output = capsys.readouterr().out

    assert output.startswith("Error: ")
    assert "schema version 99" in output
    assert goals_file.read_text(encoding="utf-8") == text


def test_main_reports_corrupt_state_file(tmp_path, monkeypatch, capsys):
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text("{not json", encoding="utf-8")

    assert run_cli(monkeypatch, tmp_path, "task", "list") == 1

    assert "is not valid JSON" in capsys.readouterr().out
    assert tasks_file.read_text(encoding="utf-8") == "{not json"


def test_main_reads_legacy_file_and_upgrades_it_on_save(
    tmp_path,
    monkeypatch,
    capsys,
):
    goals_file = tmp_path / "goals.json"
    goal = Goal.create(description="Legacy goal", project="TestProject")
    GoalRegistry(goals_file).add_goal(goal)
    items = json.loads(goals_file.read_text(encoding="utf-8"))["goals"]
    goals_file.write_text(json.dumps(items), encoding="utf-8")

    assert run_cli(monkeypatch, tmp_path, "goal", "list") == 0
    assert "Legacy goal" in capsys.readouterr().out
    assert isinstance(json.loads(goals_file.read_text(encoding="utf-8")), list)

    project_path = tmp_path / "TestProject"
    project_path.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(project_path)

    result = run_cli(
        monkeypatch,
        tmp_path,
        "goal",
        "create",
        "Second goal",
        "--project",
        "TestProject",
    )

    data = json.loads(goals_file.read_text(encoding="utf-8"))

    assert result == 0
    assert data["schema_version"] == 1
    assert len(data["goals"]) == 2


def test_main_goal_create_rejects_unregistered_project(
    tmp_path,
    monkeypatch,
    capsys,
):
    result = run_cli(
        monkeypatch,
        tmp_path,
        "goal",
        "create",
        "Orphan goal",
        "--project",
        "Ghost",
    )

    output = capsys.readouterr().out

    assert result == 1
    assert "project is not registered: Ghost" in output
    assert not (tmp_path / "goals.json").exists()


def test_main_validate_reports_goal_for_unregistered_project(
    tmp_path,
    monkeypatch,
    capsys,
):
    goal = Goal.create(description="Orphan goal", project="Ghost")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)

    result = run_cli(monkeypatch, tmp_path, "validate")

    output = capsys.readouterr().out

    assert result == 1
    assert "Validation failed." in output
    assert f"Goal {goal.id} references unregistered project: Ghost" in output


def test_main_validate_passes_once_the_project_is_registered(
    tmp_path,
    monkeypatch,
    capsys,
):
    goal = Goal.create(description="Registered goal", project="Aircursor")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    project_path = tmp_path / "Aircursor"
    project_path.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(project_path)

    result = run_cli(monkeypatch, tmp_path, "validate")

    assert result == 0
    assert "Validation passed." in capsys.readouterr().out


def test_task_requeue_command_is_registered():
    """The task requeue command takes a task ID and a reason."""
    parser = build_parser()

    args = parser.parse_args(
        ["task", "requeue", "task-123", "--reason", "worker died"],
    )

    assert args.command == "task"
    assert args.task_command == "requeue"
    assert args.task_id == "task-123"
    assert args.reason == "worker died"


def test_main_task_requeue_returns_running_task_to_ready(
    tmp_path,
    monkeypatch,
    capsys,
):
    """aic task requeue moves a running task back to ready."""
    goal = Goal.create(description="Stuck goal", project="TestProject")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    registry = TaskRegistry(tmp_path / "tasks.json")
    task = Task.create(goal_id=goal.id, title="Stuck task")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")
    registry.update_task_status(task.id, "running")

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "requeue",
        task.id,
        "--reason",
        "worker process died",
    )

    output = capsys.readouterr().out

    assert result == 0
    assert "Status: ready" in output
    assert "Reason: worker process died" in output
    assert registry.get_task(task.id).status == "ready"


def test_task_requeue_requires_a_reason(capsys):
    """The parser rejects a requeue that gives no reason."""
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["task", "requeue", "task-123"])

    assert excinfo.value.code == 2
    assert "--reason" in capsys.readouterr().err


def test_main_task_lifecycle_records_attempts(
    tmp_path,
    monkeypatch,
    capsys,
):
    """The CLI records each attempt, including one that was requeued."""
    goal = Goal.create(description="Recorded goal", project="TestProject")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Recorded task")
    TaskRegistry(tmp_path / "tasks.json").add_task(task)

    for command in ("ready", "start"):
        result = run_cli(monkeypatch, tmp_path, "task", command, task.id)
        assert result == 0

    result = run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "requeue",
        task.id,
        "--reason",
        "worker process died",
    )
    assert result == 0

    for command in ("start", "complete"):
        result = run_cli(monkeypatch, tmp_path, "task", command, task.id)
        assert result == 0

    capsys.readouterr()

    records = ExecutionRecordRegistry(
        tmp_path / "executions.json",
    ).list_attempts(task.id)

    assert [record.ended_as for record in records] == [
        "requeued",
        "completed",
    ]
    assert [record.reason for record in records] == [
        "worker process died",
        "",
    ]
    assert all(record.source == "cli" for record in records)
    assert all(record.started_at is not None for record in records)


def _register_project(data_dir, name="Aircursor"):
    """Register a project directory under the test data directory."""
    project_path = data_dir / name
    project_path.mkdir()
    ProjectRegistry(data_dir / "projects.json").add_project(project_path)


def test_main_validate_passes_for_a_recorded_lifecycle(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Records made by the CLI agree with the task status."""
    _register_project(tmp_path)
    goal = Goal.create(description="Recorded goal", project="Aircursor")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Recorded task")
    TaskRegistry(tmp_path / "tasks.json").add_task(task)

    for command in ("ready", "start"):
        result = run_cli(monkeypatch, tmp_path, "task", command, task.id)
        assert result == 0

    assert run_cli(monkeypatch, tmp_path, "validate") == 0

    assert run_cli(monkeypatch, tmp_path, "task", "complete", task.id) == 0
    assert run_cli(monkeypatch, tmp_path, "validate") == 0

    assert "Validation passed." in capsys.readouterr().out


def test_main_validate_reports_an_attempt_left_open(
    tmp_path,
    monkeypatch,
    capsys,
):
    """An open record for a task that is not running is reported."""
    _register_project(tmp_path)
    goal = Goal.create(description="Recorded goal", project="Aircursor")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Recorded task")
    TaskRegistry(tmp_path / "tasks.json").add_task(task)
    assert run_cli(monkeypatch, tmp_path, "task", "ready", task.id) == 0
    record = ExecutionRecordRegistry(
        tmp_path / "executions.json",
    ).open_attempt(task.id, "cli")
    capsys.readouterr()

    result = run_cli(monkeypatch, tmp_path, "validate")

    output = capsys.readouterr().out

    assert result == 1
    assert "Validation failed." in output
    assert (
        f"Execution record {record.id} is open but task {task.id} is ready"
        in output
    )


def test_main_validate_reports_an_unreadable_records_file(
    tmp_path,
    monkeypatch,
    capsys,
):
    """A corrupt records file is reported as an error, not a traceback."""
    (tmp_path / "executions.json").write_text("{not json", encoding="utf-8")

    result = run_cli(monkeypatch, tmp_path, "validate")

    captured = capsys.readouterr()

    assert result == 1
    assert "executions.json" in captured.out + captured.err
