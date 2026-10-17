"""Tests for the execution adapters that ship with the project."""

from aic_control_centre.execution.adapters import (
    NOOP_REASON,
    NOOP_TARGET,
    NoopAdapter,
    build_adapter_registry,
)
from aic_control_centre.execution.contract import ExecutionRequest


def test_noop_adapter_completes_the_requested_task_and_says_so():
    """The outcome is for the same task, and its reason admits no work."""
    outcome = NoopAdapter().execute(
        ExecutionRequest(task_id="task-1", target=NOOP_TARGET),
    )

    assert outcome.task_id == "task-1"
    assert outcome.outcome == "completed"
    assert outcome.reason == NOOP_REASON
    assert "no work was done" in outcome.reason


def test_the_shipped_registry_holds_only_the_noop_adapter():
    """No other adapter is registered, so nothing else can be run."""
    registry = build_adapter_registry()

    assert registry.list_targets() == [NOOP_TARGET]
    assert isinstance(registry.resolve(NOOP_TARGET), NoopAdapter)


def test_noop_adapter_describes_itself_honestly():
    """The description shown by aic task targets says no work is done."""
    assert "no work is done" in NoopAdapter.description


def test_noop_adapter_needs_no_grant():
    """It does nothing, so no project needs permission to use it."""
    assert NoopAdapter.requires_grant is False
