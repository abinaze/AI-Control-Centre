"""Tests for the shared reader of the request of a child process."""

import errno
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aic_control_centre.execution.child_request import (
    PATH_LIMIT,
    RequestRefused,
    failed,
    read_project_path,
    serve,
    shown_path,
    unreadable_outcome,
)
from aic_control_centre.execution.snapshot import escape_name
from aic_control_centre.projects.directory import (
    MISSING,
    NOT_A_DIRECTORY,
    UNREADABLE,
)


def _request(**fields):
    return json.dumps(fields).encode("utf-8")


def _usable(path):
    return None


def _refused(request, check=_usable):
    with pytest.raises(RequestRefused) as caught:
        read_project_path(request, check)

    return caught.value


def _explode(path):
    raise AssertionError("the directory was checked")


def test_a_request_that_is_not_utf8_is_refused() -> None:
    """The reason says what was wrong with the request."""
    refused = _refused(b"\xff\xfe", _explode)

    assert refused.outcome == {
        "outcome": "failed",
        "reason": "the request was not valid UTF-8",
    }


def test_a_request_that_is_not_json_is_refused() -> None:
    """Text that is not JSON, and JSON nested too deeply, are refused."""
    expected = {
        "outcome": "failed",
        "reason": "the request was not valid JSON",
    }

    assert _refused(b"not json", _explode).outcome == expected
    assert _refused(b"[" * 200000, _explode).outcome == expected


def test_a_request_without_a_usable_path_is_refused() -> None:
    """The path must be a non-empty text in a JSON object."""
    expected = {
        "outcome": "failed",
        "reason": "the request has no project path",
    }
    requests = [
        b"[1]",
        b"null",
        _request(task_id="t"),
        _request(project_path=""),
        _request(project_path=5),
        _request(project_path=None),
        _request(project_path=["a"]),
    ]

    for request in requests:
        assert _refused(request, _explode).outcome == expected


def test_a_usable_directory_returns_the_path_as_given() -> None:
    """The check is asked about the path, and other fields are ignored."""
    asked = []

    def check(path):
        asked.append(path)

        return None

    request = _request(project_path="some/where", task_id="t", target="x")

    assert read_project_path(request, check) == "some/where"
    assert asked == [Path("some/where")]
    assert isinstance(asked[0], Path)


def test_the_path_that_is_returned_is_not_the_shown_path() -> None:
    """The walk needs the real path, not the escaped and cut one."""
    path = "dir/" + "x" * 200 + "\\back\x1b"

    assert read_project_path(_request(project_path=path), _usable) == path


def test_a_missing_directory_is_reported_with_its_escaped_path() -> None:
    """The path is data, so it cannot move the cursor or hide text."""
    refused = _refused(
        _request(project_path="a\nb\x1b[2J"),
        lambda path: (MISSING, ""),
    )

    assert refused.reason == (
        "the project directory does not exist: a\\x0ab\\x1b[2J"
    )


def test_a_path_that_is_not_a_directory_is_reported() -> None:
    """A file is not a directory."""
    refused = _refused(
        _request(project_path="some/file.txt"),
        lambda path: (NOT_A_DIRECTORY, ""),
    )

    assert refused.reason == (
        "the project path is not a directory: some/file.txt"
    )


def test_a_directory_that_cannot_be_read_says_why() -> None:
    """The detail from the check is in the reason."""
    refused = _refused(
        _request(project_path="some/where"),
        lambda path: (UNREADABLE, "Permission denied"),
    )

    assert refused.reason == (
        "the project directory cannot be read: some/where; "
        "Permission denied"
    )


def test_any_other_kind_of_problem_counts_as_unreadable() -> None:
    """Only the two named kinds have their own text."""
    refused = _refused(
        _request(project_path="p"),
        lambda path: ("something else", "why"),
    )

    assert refused.reason == "the project directory cannot be read: p; why"


def test_a_backslash_in_a_path_is_doubled_in_a_reason() -> None:
    """A Windows path is shown with doubled backslashes, as names are."""
    refused = _refused(
        _request(project_path="C:\\Users\\me\\project"),
        lambda path: (MISSING, ""),
    )

    assert refused.reason == (
        "the project directory does not exist: "
        "C:\\\\Users\\\\me\\\\project"
    )


def test_a_long_path_is_cut_in_a_reason() -> None:
    """The path is shown up to the path limit and no further."""
    long_path = "/nonexistent/" + "x" * 300

    refused = _refused(
        _request(project_path=long_path),
        lambda path: (MISSING, ""),
    )

    assert refused.reason == (
        "the project directory does not exist: "
        + escape_name(long_path, limit=PATH_LIMIT)
    )
    assert "x" * 200 not in refused.reason


def test_the_path_limit_is_120_characters() -> None:
    """A reason is cut at 1000 characters, so a path must stay short."""
    assert PATH_LIMIT == 120
    assert shown_path("x" * 500) == escape_name("x" * 500, limit=120)
    assert shown_path("a\nb") == "a\\x0ab"


def test_a_refusal_carries_its_reason_and_builds_its_outcome() -> None:
    """The outcome is built fresh each time, so it can be changed safely."""
    refused = RequestRefused("because")

    assert isinstance(refused, Exception)
    assert str(refused) == "because"
    assert refused.reason == "because"
    assert refused.outcome == {"outcome": "failed", "reason": "because"}
    assert refused.outcome is not refused.outcome


def test_failed_is_a_failed_outcome_with_a_reason() -> None:
    """The answer has exactly the two fields that the parent reads."""
    assert failed("no") == {"outcome": "failed", "reason": "no"}


def test_an_error_during_the_walk_is_reported_with_its_message() -> None:
    """The message of the system is the reason."""
    assert unreadable_outcome(OSError(errno.EIO, "Input/output error")) == {
        "outcome": "failed",
        "reason": "the project directory cannot be read: Input/output error",
    }


def test_an_error_without_a_message_is_reported_by_its_type() -> None:
    """An error that has no message of its own is named by its type."""
    assert unreadable_outcome(OSError()) == {
        "outcome": "failed",
        "reason": "the project directory cannot be read: OSError",
    }


def test_the_message_of_an_error_is_escaped_and_cut() -> None:
    """The message is data, so it cannot move the cursor."""
    message = "bad\nreason" + "y" * 200

    outcome = unreadable_outcome(OSError(errno.EIO, message))

    assert outcome["reason"] == (
        "the project directory cannot be read: "
        + escape_name(message, limit=PATH_LIMIT)
    )
    assert "\n" not in outcome["reason"]


def _stdin(monkeypatch, data):
    monkeypatch.setattr(
        sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO(data)),
    )


def test_serve_prints_one_json_line_and_returns_zero(
    monkeypatch,
    capsys,
) -> None:
    """The answer goes to standard output, and the exit status is zero."""
    _stdin(monkeypatch, b"the request")
    seen = []

    def answer(request_bytes):
        seen.append(request_bytes)

        return {"outcome": "completed", "reason": "done"}

    assert serve(answer) == 0

    output = capsys.readouterr().out

    assert seen == [b"the request"]
    assert output == (
        json.dumps({"outcome": "completed", "reason": "done"}) + "\n"
    )


def test_serve_answers_a_failure_with_status_zero(
    monkeypatch,
    capsys,
) -> None:
    """A request that cannot be done is an answer, not a crash."""
    _stdin(monkeypatch, b"")

    assert serve(lambda request_bytes: failed("no")) == 0
    assert json.loads(capsys.readouterr().out) == {
        "outcome": "failed",
        "reason": "no",
    }
