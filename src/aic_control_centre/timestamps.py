"""Read the times that AI-Control-Centre stores."""

from __future__ import annotations

from datetime import datetime, timezone


def read_time(value: object) -> datetime | None:
    """Return a stored time as UTC, or None when it cannot be used.

    A stored time is ISO 8601 text with a UTC offset, as the registries
    write it. Text that is not a time, a date with no time of day, a
    time with no offset and a value that is not text are all unreadable.
    A time with no offset cannot be compared with the clock.
    """
    if not isinstance(value, str):
        return None

    try:
        moment = datetime.fromisoformat(value)

        if moment.tzinfo is None:
            return None

        return moment.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None
