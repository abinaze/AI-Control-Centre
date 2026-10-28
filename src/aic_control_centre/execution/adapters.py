"""Execution adapters that ship with AI-Control-Centre."""

from __future__ import annotations

import sys

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_COMPLETED,
    ExecutionOutcome,
)
from aic_control_centre.execution.process import ProcessAdapter
from aic_control_centre.execution.readonly import ReadOnlyAdapter
from aic_control_centre.execution.registry import ExecutionAdapterRegistry

NOOP_TARGET = "noop"
NOOP_REASON = "noop adapter: no work was done"

INSPECT_TARGET = "inspect"
INSPECT_MODULE = "aic_control_centre.execution.inspect_project"
INSPECT_DESCRIPTION = (
    "reports what is in the project directory; changes nothing"
)


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


def build_inspect_adapter() -> ReadOnlyAdapter:
    """Return the adapter that reports what is in a project directory.

    It runs a module that AIC ships, in a child process, with the Python
    that runs AIC. The child is given no PYTHONPATH, so AIC must be
    installed for it to start. The run is wrapped in a read-only check, and
    it needs a grant like any adapter that touches a project.
    """
    return ReadOnlyAdapter(
        ProcessAdapter(
            [sys.executable, "-m", INSPECT_MODULE],
            description=INSPECT_DESCRIPTION,
            requires_grant=True,
            requires_project=True,
        ),
    )


def build_adapter_registry() -> ExecutionAdapterRegistry:
    """Return a registry of every adapter the CLI can run.

    Adapters are registered here, in code. Nothing is loaded by name from
    configuration, so settings cannot make the CLI run other code.
    """
    registry = ExecutionAdapterRegistry()
    registry.register(NOOP_TARGET, NoopAdapter())
    registry.register(INSPECT_TARGET, build_inspect_adapter())

    return registry
