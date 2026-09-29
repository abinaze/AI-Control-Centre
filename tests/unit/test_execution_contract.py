"""Tests for the execution contract."""

import pytest

from aic_control_centre.execution.contract import (
    ExecutionRequest,
    ExecutionResult,
)


def test_execution_request_stores_task_id_and_target():
    """An execution request identifies its task and target."""
    request = ExecutionRequest(
        task_id="task-123",
        target="test",
    )

    assert request.task_id == "task-123"
    assert request.target == "test"


def test_execution_request_is_immutable():
    """Execution requests cannot be modified after creation."""
    request = ExecutionRequest(
        task_id="task-123",
        target="test",
    )

    with pytest.raises(AttributeError):
        request.task_id = "task-456"


@pytest.mark.parametrize("task_id", ["", "   ", "\t"])
def test_execution_request_rejects_empty_task_id(task_id):
    """Execution requests require a non-empty task ID."""
    with pytest.raises(ValueError, match="task ID cannot be empty"):
        ExecutionRequest(
            task_id=task_id,
            target="test",
        )


@pytest.mark.parametrize("target", ["", "   ", "\t"])
def test_execution_request_rejects_empty_target(target):
    """Execution requests require a non-empty target."""
    with pytest.raises(ValueError, match="execution target cannot be empty"):
        ExecutionRequest(
            task_id="task-123",
            target=target,
        )


def test_execution_result_represents_acceptance():
    """An execution result can represent an accepted request."""
    result = ExecutionResult(
        task_id="task-123",
        accepted=True,
        reason="task accepted for execution",
    )

    assert result.task_id == "task-123"
    assert result.accepted is True
    assert result.reason == "task accepted for execution"


def test_execution_result_represents_rejection():
    """An execution result can represent a rejected request."""
    result = ExecutionResult(
        task_id="task-123",
        accepted=False,
        reason="task is not ready for execution",
    )

    assert result.task_id == "task-123"
    assert result.accepted is False
    assert result.reason == "task is not ready for execution"


def test_execution_result_is_immutable():
    """Execution results cannot be modified after creation."""
    result = ExecutionResult(
        task_id="task-123",
        accepted=True,
        reason="task accepted for execution",
    )

    with pytest.raises(AttributeError):
        result.accepted = False


@pytest.mark.parametrize("task_id", ["", "   ", "\t"])
def test_execution_result_rejects_empty_task_id(task_id):
    """Execution results require a non-empty task ID."""
    with pytest.raises(ValueError, match="task ID cannot be empty"):
        ExecutionResult(
            task_id=task_id,
            accepted=False,
            reason="rejected",
        )


@pytest.mark.parametrize("reason", ["", "   ", "\t"])
def test_execution_result_rejects_empty_reason(reason):
    """Execution results require an explanation."""
    with pytest.raises(
        ValueError,
        match="execution result reason cannot be empty",
    ):
        ExecutionResult(
            task_id="task-123",
            accepted=False,
            reason=reason,
        )
