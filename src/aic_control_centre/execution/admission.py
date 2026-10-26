"""Execution admission for AI-Control-Centre."""

from __future__ import annotations

from pathlib import Path

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
