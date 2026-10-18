"""Tests for the grant information in aic task targets."""

import sys

from aic_control_centre.cli import main
from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.registry import ExecutionAdapterRegistry


class Silent:
    """An adapter that says nothing about a description or a grant."""

    def execute(self, request):
        return ExecutionOutcome(
            task_id=request.task_id,
            outcome="completed",
            reason="ran",
        )


class Described(Silent):
    description = "does a described thing"
    requires_grant = True


class Exempt(Silent):
    description = "does nothing"
    requires_grant = False


def run_cli(monkeypatch, data_dir, *arguments):
    monkeypatch.setenv("AIC_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "argv", ["aic", *arguments])

    return main()


def _offer(monkeypatch, **adapters):
    registry = ExecutionAdapterRegistry()

    for name, adapter in adapters.items():
        registry.register(name, adapter)

    monkeypatch.setattr(
        "aic_control_centre.tasks.commands.build_adapter_registry",
        lambda: registry,
    )


def test_noop_is_listed_as_needing_no_grant(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The shipped target says that nobody needs permission to use it."""
    assert run_cli(monkeypatch, tmp_path, "task", "targets") == 0

    assert (
        "noop: completes the task at once; no work is done "
        "(needs no grant)"
    ) in capsys.readouterr().out


def test_a_target_that_says_nothing_is_listed_as_needing_a_grant(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The default for an adapter is that it needs a grant."""
    _offer(monkeypatch, plain=Silent())

    assert run_cli(monkeypatch, tmp_path, "task", "targets") == 0

    assert "plain (needs a grant)" in capsys.readouterr().out


def test_a_described_target_shows_its_description_and_its_grant(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The description and the grant note share one line."""
    _offer(monkeypatch, work=Described(), idle=Exempt())

    assert run_cli(monkeypatch, tmp_path, "task", "targets") == 0

    output = capsys.readouterr().out

    assert "idle: does nothing (needs no grant)" in output
    assert "work: does a described thing (needs a grant)" in output


def test_targets_still_count_and_sort_the_targets(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """The count line and the order are unchanged."""
    _offer(monkeypatch, zeta=Silent(), alpha=Silent())

    assert run_cli(monkeypatch, tmp_path, "task", "targets") == 0

    lines = capsys.readouterr().out.splitlines()

    assert lines[0] == "Execution targets: 2"
    assert [line.split(" ")[0] for line in lines[1:]] == ["alpha", "zeta"]
