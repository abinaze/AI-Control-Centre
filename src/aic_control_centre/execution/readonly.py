"""A wrapper that checks that a run left the project as it was.

An adapter that only reads a project is wrapped in a ReadOnlyAdapter. The
wrapper takes a snapshot of the project before the run and another one
after it, and a run that changed anything is a failed outcome.

What this does and does not do:

- It detects a change inside the project. It does not prevent one.
- It sees only the project directory. A change anywhere else is not seen.
- It cannot tell who made a change, so a person who edits the project
  while the run goes on causes a failure too. The run can be requeued, and
  the reason says that the cause may be another program.
- It is not a sandbox. A grant and this check are policy for code that
  AIC ships, not a defence against a hostile program run by the same user.
- The snapshots are limited in the number of files and their size, and
  not in time. A project over the limits is refused before the run
  starts, and one that passes them during the run is a failure.
"""

from __future__ import annotations

from dataclasses import replace

from aic_control_centre.execution import snapshot as snapshot_module
from aic_control_centre.execution.contract import ExecutionRequest
from aic_control_centre.execution.outcome import (
    EXECUTION_OUTCOME_FAILED,
    ExecutionOutcome,
)
from aic_control_centre.execution.registry import ExecutionAdapter
from aic_control_centre.execution.snapshot import (
    Changes,
    SnapshotLimitError,
    compare_snapshots,
    escape_name,
    take_snapshot,
)

READ_ONLY_REASON = "the project changed during a read-only run"
NAMES_SHOWN = 3


def describe_changes(changes: Changes) -> str:
    """Return the reason for a run that changed the project.

    It gives the counts and the first few names, escaped, so it is short
    however much changed.
    """
    names = (changes.changed + changes.added + changes.removed)[:NAMES_SHOWN]
    shown = ", ".join(escape_name(name) for name in names)

    return (
        f"{READ_ONLY_REASON}: {len(changes.changed)} changed, "
        f"{len(changes.added)} added, {len(changes.removed)} removed "
        f"({shown}); the cause may be another program"
    )


def _limited_snapshot(root):
    """Take a snapshot that stops when the project passes a limit."""
    return take_snapshot(
        root,
        max_files=snapshot_module.SNAPSHOT_MAX_FILES,
        max_bytes=snapshot_module.SNAPSHOT_MAX_BYTES,
    )


def _why(error: OSError) -> str:
    """Return a short, printable reason for a file system error."""
    return escape_name(error.strerror or type(error).__name__, limit=120)


class ReadOnlyAdapter:
    """Run an adapter and fail the run if it changed the project.

    The wrapper always needs a project, and asks for a grant when the
    adapter it wraps does. Its description is the description of that
    adapter.
    """

    requires_project = True
    snapshots = True

    def __init__(self, adapter: ExecutionAdapter, take=None) -> None:
        self.adapter = adapter
        self._take = take if take is not None else _limited_snapshot

    @property
    def requires_grant(self) -> bool:
        """Return what the wrapped adapter says, true when it says nothing."""
        return getattr(self.adapter, "requires_grant", True)

    @property
    def description(self) -> str:
        """Return the description of the wrapped adapter."""
        return getattr(self.adapter, "description", "")

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        """Run the wrapped adapter between two snapshots of the project."""
        if request.project_path is None:
            return self._failed(request, "the request has no project path")

        try:
            before = self._take(request.project_path)
        except SnapshotLimitError as error:
            return self._failed(
                request,
                f"the project is too large to check, so nothing was run: "
                f"{_why(error)}",
            )
        except OSError as error:
            return self._failed(
                request,
                f"the project could not be read before the run: "
                f"{_why(error)}",
            )

        outcome = None
        problem = None

        try:
            outcome = self.adapter.execute(request)
        except Exception as error:
            problem = error

        try:
            after = self._take(request.project_path)
        except SnapshotLimitError as error:
            return self._failed(
                request,
                f"the project passed a limit during the run, so the run "
                f"could not be checked: {_why(error)}",
                outcome,
            )
        except OSError as error:
            return self._failed(
                request,
                f"the project could not be read after the run: "
                f"{_why(error)}",
            )

        changes = compare_snapshots(before, after)

        if changes:
            return self._failed(request, describe_changes(changes), outcome)

        if problem is not None:
            raise problem

        return outcome

    def _failed(
        self,
        request: ExecutionRequest,
        reason: str,
        outcome: ExecutionOutcome | None = None,
    ) -> ExecutionOutcome:
        """Return a failed outcome, keeping the attempt of an outcome."""
        if outcome is not None:
            return replace(
                outcome,
                outcome=EXECUTION_OUTCOME_FAILED,
                reason=reason,
            )

        return ExecutionOutcome(
            task_id=request.task_id,
            outcome=EXECUTION_OUTCOME_FAILED,
            reason=reason,
        )
