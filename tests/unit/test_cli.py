import json
import sys

from aic_control_centre.cli import build_parser, main
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry


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
