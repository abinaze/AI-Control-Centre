"""Grants that let a project use an execution target.

A target that does real work must not run for a project until a person
has allowed it. Admission asks a grant source, and a source that has no
grant says no, so the default is that nothing is allowed.
"""

from __future__ import annotations

from typing import Protocol


class GrantSource(Protocol):
    """Anything that can say whether a project may use a target."""

    def is_granted(self, project: str, target: str) -> bool:
        """Return whether the project has an active grant for the target."""


class NoGrants:
    """A grant source with no grants, so every request that needs one fails."""

    def is_granted(self, project: str, target: str) -> bool:
        """Return False for every project and target."""
        return False
