"""Tests for the project fields of the execution contract."""

import pytest

from aic_control_centre.execution.contract import (
    ExecutionRequest,
    ExecutionResult,
)


def test_a_request_built_by_hand_has_no_project_path() -> None:
    """Nothing is looked up, and nothing is claimed, unless it is asked."""
    request = ExecutionRequest(task_id="task-1", target="test")

    assert request.project_path is None
    assert request.requires_project is False


def test_a_request_can_carry_a_path_and_a_requirement(tmp_path) -> None:
    """Both fields are plain data on the request."""
    request = ExecutionRequest(
        task_id="task-1",
        target="test",
        requires_project=True,
        project_path=tmp_path,
    )

    assert request.requires_project is True
    assert request.project_path == tmp_path


def test_a_project_path_must_be_a_path() -> None:
    """Text is refused, so a path is never half checked."""
    with pytest.raises(ValueError, match="project path must be a path"):
        ExecutionRequest(
            task_id="task-1",
            target="test",
            project_path="/somewhere",
        )


def test_requests_without_a_path_still_compare_equal() -> None:
    """Requests that existed before the path was added are unchanged."""
    first = ExecutionRequest(task_id="task-1", target="test")
    second = ExecutionRequest(task_id="task-1", target="test")

    assert first == second


def test_a_result_has_no_project_path_unless_it_is_given(tmp_path) -> None:
    """The path on a result is optional, like the path on a request."""
    plain = ExecutionResult(task_id="task-1", accepted=True, reason="ok")
    with_path = ExecutionResult(
        task_id="task-1",
        accepted=True,
        reason="ok",
        project_path=tmp_path,
    )

    assert plain.project_path is None
    assert with_path.project_path == tmp_path
