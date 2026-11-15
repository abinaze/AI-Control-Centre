"""Execution admission for AI-Control-Centre."""

from __future__ import annotations

from pathlib import Path

from aic_control_centre.execution import snapshot as snapshot_module
from aic_control_centre.execution.contract import (
    ExecutionRequest,
    ExecutionResult,
)
from aic_control_centre.execution.grants import GrantSource, NoGrants
from aic_control_centre.execution.projects import (
    NoProjects,
    ProjectSource,
)
from aic_control_centre.projects.directory import (
    MISSING,
    NOT_A_DIRECTORY,
    directory_problem,
)
from aic_control_centre.readiness.tasks import TaskReadinessEvaluator


class ExecutionAdmission:
    """Determine whether an execution request may cross the execution boundary."""

    def __init__(
        self,
        readiness_evaluator: TaskReadinessEvaluator | None = None,
        grants: GrantSource | None = None,
        projects: ProjectSource | None = None,
    ) -> None:
        self.readiness_evaluator = (
            readiness_evaluator or TaskReadinessEvaluator()
        )
        self.grants = grants if grants is not None else NoGrants()
        self.projects = projects if projects is not None else NoProjects()

    def evaluate(self, request: ExecutionRequest) -> ExecutionResult:
        """Evaluate an execution request without executing or mutating state."""
        readiness = self.readiness_evaluator.evaluate(request.task_id)

        if not readiness.ready:
            return ExecutionResult(
                task_id=request.task_id,
                accepted=False,
                reason=readiness.reason,
            )

        project_path: Path | None = None

        if request.requires_project:
            project_path, refusal = self._project_directory(request.task_id)

            if refusal:
                return ExecutionResult(
                    task_id=request.task_id,
                    accepted=False,
                    reason=refusal,
                )

        if request.requires_grant:
            project = self._project_of(request.task_id)

            if not project or not self.grants.is_granted(
                project,
                request.target,
            ):
                return ExecutionResult(
                    task_id=request.task_id,
                    accepted=False,
                    reason=(
                        f"target {request.target} is not granted for "
                        f"project {project or 'unknown'}"
                    ),
                )

        if request.snapshots and project_path is not None:
            refusal = self._snapshot_refusal(request.task_id, project_path)

            if refusal:
                return ExecutionResult(
                    task_id=request.task_id,
                    accepted=False,
                    reason=refusal,
                )

        return ExecutionResult(
            task_id=request.task_id,
            accepted=True,
            reason="task accepted for execution",
            project_path=project_path,
        )

    def _project_of(self, task_id: str) -> str:
        """Return the name of the project that a task belongs to."""
        task = self.readiness_evaluator.task_registry.get_task(task_id)

        if task is None:
            return ""

        goal = self.readiness_evaluator.goal_registry.get_goal(task.goal_id)

        if goal is None:
            return ""

        return goal.project

    def _project_directory(
        self,
        task_id: str,
    ) -> tuple[Path | None, str]:
        """Return the directory of the task's project, or why not.

        The second value is empty when the directory can be used. The
        directory is only looked at. Nothing is opened or written.
        """
        name = self._project_of(task_id)

        if not name:
            return None, "the project of the task is unknown"

        project = self.projects.get_project(name)

        if project is None:
            return None, f"project {name} is not registered"

        problem = directory_problem(project.path)

        if problem is None:
            return project.path, ""

        kind, detail = problem

        if kind == MISSING:
            return None, (
                f"the directory of project {name} does not exist: "
                f"{project.path}"
            )

        if kind == NOT_A_DIRECTORY:
            return None, (
                f"the path of project {name} is not a directory: "
                f"{project.path}"
            )

        return None, (
            f"the directory of project {name} cannot be read: "
            f"{project.path}; {detail}"
        )

    def _snapshot_refusal(self, task_id: str, path: Path) -> str:
        """Return why a project is too large to snapshot, or an empty string.

        Only the status of each name is read, and the count stops as soon
        as a limit is passed, so this costs little. Nothing is opened or
        written.
        """
        max_files = snapshot_module.SNAPSHOT_MAX_FILES
        max_bytes = snapshot_module.SNAPSHOT_MAX_BYTES
        name = self._project_of(task_id)

        try:
            survey = snapshot_module.survey_project(
                path,
                max_files,
                max_bytes,
            )
        except OSError as error:
            return (
                f"the directory of project {name} cannot be read: "
                f"{path}; {error.strerror or type(error).__name__}"
            )

        if not survey.exceeded:
            return ""

        if survey.exceeded == snapshot_module.LIMIT_FILES:
            limit = snapshot_module.limit_text(
                snapshot_module.LIMIT_FILES,
                max_files,
            )
        else:
            limit = snapshot_module.limit_text(
                snapshot_module.LIMIT_BYTES,
                max_bytes,
            )

        reason = (
            f"project {name} has more than {limit}, which is too much to "
            f"check before and after a read-only run; the files were "
            f"counted until the limit was passed"
        )

        if survey.folders:
            shown = ", ".join(
                f"{snapshot_module.escape_name(folder)} ({count:,})"
                for folder, count in survey.folders
            )
            reason += f"; the folders with the most files so far: {shown}"

        return reason + "; register a directory with fewer files as the project"
