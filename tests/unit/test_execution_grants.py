"""Tests for the grants that let a project use an execution target."""

import pytest

from aic_control_centre.execution.adapters import NoopAdapter
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.coordinator import ExecutionCoordinator
from aic_control_centre.execution.registry import ExecutionAdapterRegistry
from aic_control_centre.execution.start import ExecutionStartResult


class SpyStarter:
    """A starter that records the requests it is given and starts nothing."""

    def __init__(self):
        self.requests = []

    def start(self, request):
        self.requests.append(request)

        return ExecutionStartResult(
            task_id=request.task_id,
            started=False,
            reason="spy",
        )


class PlainAdapter:
    """An adapter that says nothing about grants."""

    def execute(self, request):
        raise AssertionError("the spy never starts a run")


class NeedsGrantAdapter(PlainAdapter):
    requires_grant = True


class NoGrantNeededAdapter(PlainAdapter):
    requires_grant = False


def _coordinator(adapter):
    adapters = ExecutionAdapterRegistry()
    adapters.register("target", adapter)
    spy = SpyStarter()
    coordinator = ExecutionCoordinator(
        adapter_registry=adapters,
        starter=spy,
        outcome_recorder=object(),
    )

    return coordinator, spy


@pytest.mark.parametrize(
    ("adapter", "expected"),
    [
        (NoopAdapter(), False),
        (NoGrantNeededAdapter(), False),
        (NeedsGrantAdapter(), True),
        (PlainAdapter(), True),
    ],
)
def test_coordinator_sends_the_request_marked_by_the_adapter(
    adapter,
    expected,
) -> None:
    """An adapter that says nothing is treated as needing a grant."""
    coordinator, spy = _coordinator(adapter)

    coordinator.coordinate(ExecutionRequest(task_id="task-1", target="target"))

    assert [request.requires_grant for request in spy.requests] == [expected]


@pytest.mark.parametrize(
    ("adapter", "asked", "expected"),
    [
        (PlainAdapter(), False, True),
        (NoGrantNeededAdapter(), True, False),
    ],
)
def test_the_adapter_decides_not_the_caller(adapter, asked, expected) -> None:
    """A caller cannot switch off the check for an adapter that needs it."""
    coordinator, spy = _coordinator(adapter)

    coordinator.coordinate(
        ExecutionRequest(
            task_id="task-1",
            target="target",
            requires_grant=asked,
        ),
    )

    assert [request.requires_grant for request in spy.requests] == [expected]
