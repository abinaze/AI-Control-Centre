"""Persistent grant registry for AI-Control-Centre."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from aic_control_centre.permissions.model import Grant
from aic_control_centre.storage import (
    StateFileError,
    read_state_items_or_empty,
    serialize_state_items,
    write_text_atomic,
)

PERMISSIONS_FILE_NAME = "permissions.json"


class PermissionRegistry:
    """Manage the persistent local grant registry.

    It can be given to execution admission as its grant source. The file
    path is always given explicitly, so a registry cannot point at the
    real data directory by accident. Use beside() to place the file next
    to a task registry's file.

    The registry keeps its own rules: a grant needs a project, a target
    and a reason, a pair that is already granted cannot be granted again,
    and only an active grant can be revoked. Whether the project and the
    target exist is for the caller to check.
    """

    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path

    @classmethod
    def beside(cls, task_registry_path: Path) -> PermissionRegistry:
        """Return the registry stored next to a task registry file."""
        return cls(task_registry_path.with_name(PERMISSIONS_FILE_NAME))

    def _load(self) -> list[Grant]:
        """Load grants from disk."""
        data = read_state_items_or_empty(
            self.registry_path,
            "permissions",
        )

        try:
            return [
                Grant(
                    id=item["id"],
                    project=item["project"],
                    target=item["target"],
                    granted_at=item["granted_at"],
                    reason=item["reason"],
                    revoked_at=item["revoked_at"],
                )
                for item in data
            ]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise StateFileError(
                f"{self.registry_path} has an invalid grant: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def _save(self, grants: list[Grant]) -> None:
        """Persist grants to disk."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        write_text_atomic(
            self.registry_path,
            serialize_state_items(
                "permissions",
                [asdict(grant) for grant in grants],
            ),
        )

    def list_grants(self, include_revoked: bool = False) -> list[Grant]:
        """Return grants, oldest first.

        Revoked grants are left out unless include_revoked is set.
        """
        return [
            grant
            for grant in self._load()
            if include_revoked or grant.is_active
        ]

    def is_granted(self, project: str, target: str) -> bool:
        """Return whether the project has an active grant for the target."""
        return any(
            grant.is_active
            and grant.project == project
            and grant.target == target
            for grant in self._load()
        )

    def grant(self, project: str, target: str, reason: str) -> Grant:
        """Record that a project may use a target.

        A grant that is already active for the same project and target
        is refused rather than repeated.
        """
        new_grant = Grant.create(project, target, reason)
        grants = self._load()

        for existing in grants:
            if (
                existing.is_active
                and existing.project == new_grant.project
                and existing.target == new_grant.target
            ):
                raise ValueError(
                    f"target {new_grant.target} is already granted for "
                    f"project {new_grant.project}"
                )

        grants.append(new_grant)
        self._save(grants)

        return new_grant

    def revoke(self, project: str, target: str) -> list[Grant]:
        """Revoke the active grant for a project and target.

        Every active grant for the pair is revoked, so that a file edited
        by hand into holding two cannot leave one behind. The revoked
        grants stay in the file as history.
        """
        project_name = project.strip()
        target_name = target.strip()
        grants = self._load()
        revoked: list[Grant] = []

        for index, existing in enumerate(grants):
            if (
                existing.is_active
                and existing.project == project_name
                and existing.target == target_name
            ):
                grants[index] = existing.revoke()
                revoked.append(grants[index])

        if not revoked:
            raise ValueError(
                f"target {target_name} is not granted for "
                f"project {project_name}"
            )

        self._save(grants)

        return revoked
