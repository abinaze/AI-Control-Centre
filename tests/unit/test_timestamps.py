"""Tests for the shared time reader."""

from datetime import datetime, timedelta, timezone

import pytest

from aic_control_centre.tasks.model import utc_now
from aic_control_centre.timestamps import read_time

UTC_MOMENT = datetime(2026, 10, 19, 9, 0, 0, tzinfo=timezone.utc)


def test_a_utc_time_is_read() -> None:
    """The form that the registries write is readable."""
    assert read_time("2026-10-19T09:00:00+00:00") == UTC_MOMENT


def test_a_time_written_by_the_registries_is_readable() -> None:
    """utc_now is the writer, so its output must always be accepted."""
    assert read_time(utc_now()) is not None


def test_another_offset_is_converted_to_utc() -> None:
    """The result is always in UTC."""
    moment = read_time("2026-10-19T14:00:00+05:00")

    assert moment == UTC_MOMENT
    assert moment.utcoffset() == timedelta(0)


def test_a_z_suffix_means_utc() -> None:
    """Zulu time is accepted."""
    assert read_time("2026-10-19T09:00:00Z") == UTC_MOMENT


def test_fractional_seconds_are_accepted() -> None:
    """The microseconds that utc_now writes are read."""
    moment = read_time("2026-10-19T09:00:00.650941+00:00")

    assert moment == UTC_MOMENT + timedelta(microseconds=650941)


@pytest.mark.parametrize(
    "value",
    [
        "garbage",
        "",
        " ",
        "2026-10-19",
        "2026-10-19T09:00:00",
        "2026-13-45T00:00:00+00:00",
        "2026-10-19T25:00:00+00:00",
        "2026-10-19T09:00:00+99:00",
        "0001-01-01T00:00:00+05:00",
    ],
)
def test_text_that_is_not_a_usable_time_is_unreadable(value) -> None:
    """A bad time, a bare date, a time with no offset or one that cannot
    be converted is not readable."""
    assert read_time(value) is None


@pytest.mark.parametrize("value", [None, 5, 1.5, b"2026-10-19", [], {}])
def test_a_value_that_is_not_text_is_unreadable(value) -> None:
    """A null or a number in a hand-edited file is not a time."""
    assert read_time(value) is None
