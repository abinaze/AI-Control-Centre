"""Execution adapters that ship with AI-Control-Centre."""

from __future__ import annotations

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_COMPLETED,
    ExecutionOutcome,
)
from aic_control_centre.execution.registry import ExecutionAdapterRegistry

NOOP_TARGET = "noop"
NOOP_REASON = "noop adapter: no work was done"


class NoopAdapter:
    """Complete a task at once without doing any work.

    It proves the path from the CLI to an adapter and back, and it is
    harmless. It can mark a task completed when nothing happened, so its
    reason says so, and so does the description shown by aic task targets.
    """

    description = "completes the task at once; no work is done"

    # It does nothing, so no project needs permission to use it.
    requires_grant = False

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        """Return a completed outcome for the requested task."""
        return ExecutionOutcome(
            task_id=request.task_id,
            outcome=EXECUTION_OUTCOME_COMPLETED,
            reason=NOOP_REASON,
        )


def build_adapter_registry() -> ExecutionAdapterRegistry:
    """Return a registry of every adapter the CLI can run.

    Adapters are registered here, in code. Nothing is loaded by name from
    configuration, so settings cannot make the CLI run other code.
    """
    registry = ExecutionAdapterRegistry()
    registry.register(NOOP_TARGET, NoopAdapter())

    return registry
