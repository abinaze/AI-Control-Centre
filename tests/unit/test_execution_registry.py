"""Tests for execution adapter registration and resolution."""

import pytest

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import ExecutionOutcome
from aic_control_centre.execution.registry import ExecutionAdapterRegistry


class FakeExecutionAdapter:
    """Test adapter used to verify registry behavior."""

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        return ExecutionOutcome(
            task_id=request.task_id,
            outcome="completed",
        )


def test_registry_resolves_registered_adapter():
    """A registered target resolves to its adapter."""
    adapter = FakeExecutionAdapter()
    registry = ExecutionAdapterRegistry()

    registry.register("test", adapter)

    assert registry.resolve("test") is adapter


def test_registry_supports_multiple_targets():
    """Different targets resolve to their respective adapters."""
    first = FakeExecutionAdapter()
    second = FakeExecutionAdapter()
    registry = ExecutionAdapterRegistry()

    registry.register("first", first)
    registry.register("second", second)

    assert registry.resolve("first") is first
    assert registry.resolve("second") is second


@pytest.mark.parametrize("target", ["", "   ", "\t"])
def test_registry_rejects_empty_target(target):
    """The registry requires a non-empty target."""
    registry = ExecutionAdapterRegistry()

    with pytest.raises(ValueError, match="execution target cannot be empty"):
        registry.register(target, FakeExecutionAdapter())


def test_registry_rejects_duplicate_target():
    """A target cannot be registered more than once."""
    registry = ExecutionAdapterRegistry()

    registry.register("test", FakeExecutionAdapter())

    with pytest.raises(
        ValueError,
        match="execution target already registered",
    ):
        registry.register("test", FakeExecutionAdapter())


def test_registry_rejects_unknown_target():
    """An unknown target cannot be resolved."""
    registry = ExecutionAdapterRegistry()

    with pytest.raises(KeyError, match="unknown execution target"):
        registry.resolve("missing")
