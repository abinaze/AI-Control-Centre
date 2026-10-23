"""Execution contract for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecutionRequest:
    """Describe a request to execute a persisted task.

    requires_grant says whether the target needs a grant for the project
    of the task. It defaults to True, so a request built by hand is checked.
    The coordinator sets it from the adapter it resolves.

    requires_project says whether the target acts on the directory of the
    project of the task. It defaults to False. When it is True, admission
    checks that the project is registered and that its directory exists,
    and the coordinator gives the adapter the registered path in
    project_path. A request built by hand has no path, and the coordinator
    ignores a path that a caller sets.
    """

    task_id: str
    target: str
    requires_grant: bool = True
    requires_project: bool = False
    project_path: Path | None = None

    def __post_init__(self) -> None:
        """Reject requests without required execution identifiers."""
        if not self.task_id.strip():
            raise ValueError("task ID cannot be empty")

        if not self.target.strip():
            raise ValueError("execution target cannot be empty")

        if self.project_path is not None and not isinstance(
            self.project_path,
            Path,
        ):
            raise ValueError("project path must be a path")


@dataclass(frozen=True)
class ExecutionResult:
    """Describe the outcome of an execution-boundary decision.

    An accepted result for a request that needs a project carries the
    registered path of its directory.
    """

    task_id: str
    accepted: bool
    reason: str
    project_path: Path | None = None

    def __post_init__(self) -> None:
        """Reject results without a task identifier or reason."""
        if not self.task_id.strip():
            raise ValueError("task ID cannot be empty")

        if not self.reason.strip():
            raise ValueError("execution result reason cannot be empty")
