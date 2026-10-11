"""Tests for the state lock around CLI commands."""

import argparse
import os
import subprocess
import sys
import time

import pytest

from aic_control_centre import cli, locking
from aic_control_centre.cli import build_parser, main
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.registry import TaskRegistry

LOCK_FILE = ".aic.lock"

LOCKING_COMMANDS = {
    "validate",
    "project add",
    "goal create",
    "goal status",
    "task create",
    "task ready",
    "task start",
    "task complete",
    "task fail",
    "task requeue",
}

READ_ONLY = {
    "doctor",
    "project list",
    "goal list",
    "task list",
    "task status",
    "task readiness",
    "task history",
}


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _choices(parser):
    """Return the subcommands of a parser by name."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)

    return {}


def _parser_commands(parser):
    """Return every command the parser knows, as READ_ONLY spells them."""
    commands = set()

    for name, subparser in _choices(parser).items():
        subcommands = _choices(subparser)

        if subcommands:
            commands.update(f"{name} {sub}" for sub in subcommands)
        else:
            commands.add(name)

    return commands


def _namespace(command):
    """Build the arguments the parser would produce for a command."""
    name, _, subcommand = command.partition(" ")

    if subcommand:
        return argparse.Namespace(
            command=name,
            **{f"{name}_command": subcommand},
        )

    return argparse.Namespace(command=name)


def test_every_parser_command_is_classified() -> None:
    """A command cannot be added without deciding whether it locks."""
    known = _parser_commands(build_parser())

    assert known == LOCKING_COMMANDS | READ_ONLY
    assert LOCKING_COMMANDS.isdisjoint(READ_ONLY)
    assert cli.READ_ONLY_COMMANDS == READ_ONLY


def test_only_read_only_commands_skip_the_lock() -> None:
    """Every other command locks, including one nobody has classified."""
    for command in LOCKING_COMMANDS:
        assert cli._needs_state_lock(_namespace(command)), command

    for command in READ_ONLY:
        assert not cli._needs_state_lock(_namespace(command)), command

    assert cli._needs_state_lock(_namespace("not-a-command"))
    assert cli._needs_state_lock(_namespace("task not-a-subcommand"))


def test_commands_that_only_print_help_take_no_lock(
    tmp_path,
    monkeypatch,
) -> None:
    """With no command, or a group without a subcommand, nothing is made."""
    data_dir = tmp_path / "data"

    assert run_cli(monkeypatch, data_dir) == 0

    with pytest.raises(SystemExit):
        run_cli(monkeypatch, data_dir, "task")

    assert not data_dir.exists()


def test_writing_command_leaves_only_its_lock_and_state_file(
    tmp_path,
    monkeypatch,
) -> None:
    """The lock file is created in the data directory and nowhere else."""
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    project.mkdir()

    assert run_cli(monkeypatch, data_dir, "project", "add", str(project)) == 0

    assert sorted(path.name for path in data_dir.iterdir()) == [
        LOCK_FILE,
        "projects.json",
    ]
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "data",
        "project",
    ]


def test_read_only_command_creates_no_lock_file(
    tmp_path,
    monkeypatch,
) -> None:
    """Listing does not touch the lock."""
    data_dir = tmp_path / "data"

    assert run_cli(monkeypatch, data_dir, "goal", "list") == 0

    assert not (data_dir / LOCK_FILE).exists()


def test_writing_command_fails_cleanly_while_the_lock_is_held(
    tmp_path,
    monkeypatch,
    capsys,
    start_lock_holder,
) -> None:
    """A command that cannot get the lock changes nothing and exits 1."""
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    project.mkdir()
    holder = start_lock_holder(data_dir)
    monkeypatch.setattr(locking, "DEFAULT_LOCK_TIMEOUT", 0.3)

    result = run_cli(monkeypatch, data_dir, "project", "add", str(project))

    assert result == 1
    assert capsys.readouterr().out.strip() == (
        "Error: another aic process is using the state files (waited 0.3s)."
    )
    assert not (data_dir / "projects.json").exists()

    holder.kill()
    holder.wait()
    monkeypatch.setattr(locking, "DEFAULT_LOCK_TIMEOUT", 10.0)

    assert run_cli(monkeypatch, data_dir, "project", "add", str(project)) == 0
    assert (data_dir / "projects.json").exists()


def test_validate_waits_for_the_lock(
    tmp_path,
    monkeypatch,
    capsys,
    start_lock_holder,
) -> None:
    """validate reads four files, so it takes the lock and waits."""
    start_lock_holder(tmp_path, seconds=2)
    started = time.monotonic()

    result = run_cli(monkeypatch, tmp_path, "validate")

    assert result == 0
    assert time.monotonic() - started >= 0.5
    assert "Validation passed." in capsys.readouterr().out


def test_read_only_command_runs_while_the_lock_is_held(
    tmp_path,
    monkeypatch,
    capsys,
    start_lock_holder,
) -> None:
    """A read-only command does not wait for the lock."""
    start_lock_holder(tmp_path)
    monkeypatch.setattr(locking, "DEFAULT_LOCK_TIMEOUT", 0.3)

    assert run_cli(monkeypatch, tmp_path, "goal", "list") == 0
    assert "Error" not in capsys.readouterr().out


def test_concurrent_commands_lose_no_tasks(tmp_path) -> None:
    """Many aic processes creating tasks at once store every task.

    Without the lock the processes overwrite each other's task file and
    most of the tasks are lost, while every command still exits 0.
    """
    project = tmp_path / "project"
    project.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(project)
    goal = Goal.create(description="Concurrent goal", project="project")
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    environment = {**os.environ, "AIC_DATA_DIR": str(tmp_path)}
    count = 8

    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "aic_control_centre.cli",
                "task",
                "create",
                "--goal",
                goal.id,
                f"task {number}",
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for number in range(count)
    ]
    outputs = [process.communicate(timeout=120) for process in processes]

    assert [process.returncode for process in processes] == [0] * count, [
        output for output in outputs if output[1]
    ]

    stored = TaskRegistry(tmp_path / "tasks.json").list_tasks()

    assert sorted(task.title for task in stored) == sorted(
        f"task {number}" for number in range(count)
    )
