"""Grant model for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from aic_control_centre.tasks.model import utc_now

_REQUIRED_TEXT_FIELDS = ("id", "project", "target", "granted_at", "reason")


@dataclass(frozen=True)
class Grant:
    """Record that a project may use an execution target.

    A grant is active until it is revoked. Revoking keeps the record, so
    the history of what was allowed, when and why is not lost.
    """

    id: str
    project: str
    target: str
    granted_at: str
    reason: str
    revoked_at: str | None = None

    def __post_init__(self) -> None:
        """Reject incomplete grants."""
        for name in _REQUIRED_TEXT_FIELDS:
            value = getattr(self, name)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"grant {name} cannot be empty")

        if self.revoked_at is not None and (
            not isinstance(self.revoked_at, str)
            or not self.revoked_at.strip()
        ):
            raise ValueError("grant revoked_at cannot be empty")

    @property
    def is_active(self) -> bool:
        """Return True until the grant is revoked."""
        return self.revoked_at is None

    @classmethod
    def create(cls, project: str, target: str, reason: str) -> Grant:
        """Return a new active grant that is made now."""
        return cls(
            id=str(uuid4()),
            project=project.strip(),
            target=target.strip(),
            granted_at=utc_now(),
            reason=reason.strip(),
        )

    def revoke(self) -> Grant:
        """Return a copy of this grant that is revoked now."""
        if not self.is_active:
            raise ValueError("grant is already revoked")

        return replace(self, revoked_at=utc_now())
