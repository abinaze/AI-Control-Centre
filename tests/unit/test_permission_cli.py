"""Tests for the aic permission commands."""

import os
import subprocess
import sys

import pytest

from aic_control_centre import locking
from aic_control_centre.cli import main
from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.goals.model import Goal
from aic_control_centre.goals.registry import GoalRegistry
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.model import Task
from aic_control_centre.tasks.registry import TaskRegistry


class NeedsGrant:
    """An adapter that says nothing about grants, so it needs one."""

    def __init__(self):
        self.calls = 0

    def execute(self, request):
        self.calls += 1

        return ExecutionOutcome(
            task_id=request.task_id,
            outcome="completed",
            reason="ran",
        )


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _project(tmp_path, name="alpha"):
    path = tmp_path / name
    path.mkdir()
    ProjectRegistry(tmp_path / "projects.json").add_project(path)


def _offer_child_target(monkeypatch):
    """Register a target 'child' that needs a grant, for both commands."""
    adapter = NeedsGrant()
    adapters = ExecutionAdapterRegistry()
    adapters.register("child", adapter)

    for module in ("permissions.commands", "tasks.commands"):
        monkeypatch.setattr(
            f"aic_control_centre.{module}.build_adapter_registry",
            lambda: adapters,
        )

    return adapter


def _ready_task(tmp_path, project="alpha"):
    goal = Goal.create(description="Granted goal", project=project)
    GoalRegistry(tmp_path / "goals.json").add_goal(goal)
    task = Task.create(goal_id=goal.id, title="Granted task")
    registry = TaskRegistry(tmp_path / "tasks.json")
    registry.add_task(task)
    registry.update_task_status(task.id, "ready")

    return task


def test_a_group_without_a_subcommand_prints_help_and_takes_no_lock(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """aic permission alone only prints help."""
    data_dir = tmp_path / "data"

    with pytest.raises(SystemExit) as raised:
        run_cli(monkeypatch, data_dir, "permission")

    assert raised.value.code == 0
    assert "grant" in capsys.readouterr().out
    assert not data_dir.exists()


def test_grant_list_and_revoke_through_the_cli(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The three commands work together on the real registry."""
    _project(tmp_path)

    assert run_cli(
        monkeypatch,
        tmp_path,
        "permission",
        "grant",
        "alpha",
        "--target",
        "noop",
        "--reason",
        "trying it out",
    ) == 0
    assert "Permission granted." in capsys.readouterr().out

    assert run_cli(monkeypatch, tmp_path, "permission", "list") == 0

    listing = capsys.readouterr().out

    assert "Target: noop" in listing
    assert "Reason: trying it out" in listing

    assert run_cli(
        monkeypatch,
        tmp_path,
        "permission",
        "revoke",
        "alpha",
        "--target",
        "noop",
    ) == 0
    assert "Permission revoked." in capsys.readouterr().out

    assert run_cli(monkeypatch, tmp_path, "permission", "list") == 0
    assert "No permissions granted." in capsys.readouterr().out

    assert run_cli(
        monkeypatch,
        tmp_path,
        "permission",
        "list",
        "--all",
    ) == 0
    assert "Status: revoked" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [
        ["permission", "grant", "alpha", "--reason", "why"],
        ["permission", "grant", "alpha", "--target", "noop"],
        ["permission", "revoke", "alpha"],
        ["permission", "grant", "--target", "noop", "--reason", "why"],
    ],
)
def test_a_missing_argument_is_a_usage_error(
    tmp_path,
    monkeypatch,
    arguments,
) -> None:
    """The project, the target and the reason are all required."""
    with pytest.raises(SystemExit) as raised:
        run_cli(monkeypatch, tmp_path, *arguments)

    assert raised.value.code == 2
    assert not (tmp_path / "permissions.json").exists()


def test_grant_for_an_unregistered_project_exits_1(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The CLI reports the typo instead of recording it."""
    result = run_cli(
        monkeypatch,
        tmp_path,
        "permission",
        "grant",
        "ghost",
        "--target",
        "noop",
        "--reason",
        "why",
    )

    assert result == 1
    assert "project is not registered: ghost" in capsys.readouterr().out
    assert not (tmp_path / "permissions.json").exists()


def test_validate_passes_after_a_grant_made_through_the_cli(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """A grant made by the command is one that validation accepts."""
    _project(tmp_path)
    run_cli(
        monkeypatch,
        tmp_path,
        "permission",
        "grant",
        "alpha",
        "--target",
        "noop",
        "--reason",
        "why",
    )
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, "validate") == 0
    assert "Validation passed." in capsys.readouterr().out


def test_a_grant_made_through_the_cli_lets_a_run_start(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Grant allows the run, and revoke stops the next one."""
    _project(tmp_path)
    adapter = _offer_child_target(monkeypatch)
    task = _ready_task(tmp_path)
    run = ["task", "run", task.id, "--target", "child"]

    assert run_cli(monkeypatch, tmp_path, *run) == 1
    assert "is not granted for project alpha" in capsys.readouterr().out
    assert adapter.calls == 0

    assert run_cli(
        monkeypatch,
        tmp_path,
        "permission",
        "grant",
        "alpha",
        "--target",
        "child",
        "--reason",
        "trusted",
    ) == 0
    capsys.readouterr()

    assert run_cli(monkeypatch, tmp_path, *run) == 0
    assert "Result: completed" in capsys.readouterr().out
    assert adapter.calls == 1

    other = _ready_task(tmp_path)

    assert run_cli(
        monkeypatch,
        tmp_path,
        "permission",
        "revoke",
        "alpha",
        "--target",
        "child",
    ) == 0
    capsys.readouterr()

    assert run_cli(
        monkeypatch,
        tmp_path,
        "task",
        "run",
        other.id,
        "--target",
        "child",
    ) == 1
    assert adapter.calls == 1


def test_list_runs_while_the_lock_is_held(
    tmp_path,
    monkeypatch,
    capsys,
    start_lock_holder,
) -> None:
    """Listing is read-only, so it does not wait for the lock."""
    start_lock_holder(tmp_path)
    monkeypatch.setattr(locking, "DEFAULT_LOCK_TIMEOUT", 0.3)

    assert run_cli(monkeypatch, tmp_path, "permission", "list") == 0
    assert "No permissions granted." in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [
        ["permission", "grant", "alpha", "--target", "noop", "--reason", "x"],
        ["permission", "revoke", "alpha", "--target", "noop"],
    ],
)
def test_grant_and_revoke_wait_for_the_lock_and_change_nothing(
    tmp_path,
    monkeypatch,
    capsys,
    start_lock_holder,
    arguments,
) -> None:
    """A command that cannot get the lock exits 1 and writes nothing."""
    _project(tmp_path)
    start_lock_holder(tmp_path)
    monkeypatch.setattr(locking, "DEFAULT_LOCK_TIMEOUT", 0.3)

    assert run_cli(monkeypatch, tmp_path, *arguments) == 1
    assert "another aic process is using the state files" in (
        capsys.readouterr().out
    )
    assert not (tmp_path / "permissions.json").exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["permission", "list"],
        ["permission", "grant", "alpha", "--target", "noop", "--reason", "x"],
        ["permission", "revoke", "alpha", "--target", "noop"],
    ],
)
def test_an_unreadable_grants_file_is_reported_not_overwritten(
    tmp_path,
    monkeypatch,
    capsys,
    arguments,
) -> None:
    """A damaged file ends the command with an error and is left alone."""
    _project(tmp_path)
    (tmp_path / "permissions.json").write_text("{not json", encoding="utf-8")

    assert run_cli(monkeypatch, tmp_path, *arguments) == 1

    assert "permissions.json" in capsys.readouterr().out
    assert (tmp_path / "permissions.json").read_text("utf-8") == "{not json"


def test_eight_grants_at_once_lose_none(tmp_path, monkeypatch, capsys) -> None:
    """Eight aic permission grant processes at once all take effect."""
    names = [f"project{number}" for number in range(8)]

    for name in names:
        _project(tmp_path, name)

    environment = {**os.environ, "AIC_DATA_DIR": str(tmp_path)}
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "aic_control_centre.cli",
                "permission",
                "grant",
                name,
                "--target",
                "noop",
                "--reason",
                "parallel",
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for name in names
    ]
    outputs = [process.communicate(timeout=120) for process in processes]

    assert [process.returncode for process in processes] == [0] * 8, outputs

    grants = PermissionRegistry(tmp_path / "permissions.json").list_grants()

    assert sorted(grant.project for grant in grants) == sorted(names)
    assert run_cli(monkeypatch, tmp_path, "validate") == 0
    assert "Validation passed." in capsys.readouterr().out
