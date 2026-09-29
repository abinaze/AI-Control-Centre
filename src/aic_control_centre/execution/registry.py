"""Execution adapter registration and resolution."""

from __future__ import annotations

from typing import Protocol

from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import ExecutionOutcome


class ExecutionAdapter(Protocol):
    """Boundary for a component that performs execution."""

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        """Execute a request and return its outcome."""
        ...


class ExecutionAdapterRegistry:
    """Register and resolve execution adapters by target."""

    def __init__(self) -> None:
        self._adapters: dict[str, ExecutionAdapter] = {}

    def register(self, target: str, adapter: ExecutionAdapter) -> None:
        """Register an adapter for a unique execution target."""
        if not target.strip():
            raise ValueError("execution target cannot be empty")

        if target in self._adapters:
            raise ValueError("execution target already registered")

        self._adapters[target] = adapter

    def list_targets(self) -> list[str]:
        """Return registered execution targets in deterministic order."""
        return sorted(self._adapters)

    def resolve(self, target: str) -> ExecutionAdapter:
        """Resolve the adapter registered for a target."""
        if not target.strip():
            raise ValueError("execution target cannot be empty")

        try:
            return self._adapters[target]
        except KeyError as exc:
            raise KeyError("unknown execution target") from exc
