"""CLI commands for execution permissions."""

from __future__ import annotations

from aic_control_centre.execution.adapters import build_adapter_registry
from aic_control_centre.permissions.registry import PermissionRegistry
from aic_control_centre.projects.registry import ProjectRegistry
from aic_control_centre.tasks.registry import TaskRegistry


def _registry() -> PermissionRegistry:
    """Return the grant registry stored next to the task file."""
    return PermissionRegistry.beside(TaskRegistry().registry_path)


def grant_permission(project: str, target: str, reason: str) -> int:
    """Let a registered project use a registered execution target."""
    project_name = project.strip()
    target_name = target.strip()

    if not project_name:
        print("Error: project cannot be empty.")
        return 1

    if not target_name:
        print("Error: target cannot be empty.")
        return 1

    if not reason.strip():
        print("Error: reason cannot be empty.")
        return 1

    if ProjectRegistry().get_project(project_name) is None:
        print(f"Error: project is not registered: {project_name}")
        print("Register it first with: aic project add <path>")
        return 1

    adapters = build_adapter_registry()

    if target_name not in adapters.list_targets():
        print(f"Error: target is not registered: {target_name}")
        print("See the targets with: aic task targets")
        return 1

    try:
        grant = _registry().grant(project_name, target_name, reason)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    print("Permission granted.")
    print(f"ID: {grant.id}")
    print(f"Project: {grant.project}")
    print(f"Target: {grant.target}")
    print(f"Reason: {grant.reason}")

    adapter = adapters.resolve(target_name)

    if not getattr(adapter, "requires_grant", True):
        print(
            f"Note: target {target_name} needs no grant, "
            "so this changes nothing."
        )

    return 0


def revoke_permission(project: str, target: str) -> int:
    """End the active grant of a project for an execution target.

    A grant is revoked even when its project or its target is no longer
    registered, so that a grant can always be withdrawn.
    """
    project_name = project.strip()
    target_name = target.strip()

    if not project_name:
        print("Error: project cannot be empty.")
        return 1

    if not target_name:
        print("Error: target cannot be empty.")
        return 1

    try:
        revoked = _registry().revoke(project_name, target_name)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    print("Permission revoked.")
    print(f"Project: {project_name}")
    print(f"Target: {target_name}")

    for grant in revoked:
        print(f"ID: {grant.id}")

    return 0


def list_permissions(include_revoked: bool = False) -> int:
    """List the grants that are active, or all of them."""
    grants = _registry().list_grants(include_revoked=include_revoked)

    if not grants:
        if include_revoked:
            print("No permissions recorded.")
        else:
            print("No permissions granted.")

        return 0

    print("All permissions:" if include_revoked else "Granted permissions:")
    print()

    for grant in grants:
        print(f"- {grant.id}")
        print(f"  Project: {grant.project}")
        print(f"  Target: {grant.target}")
        print(f"  Status: {'active' if grant.is_active else 'revoked'}")
        print(f"  Reason: {grant.reason}")
        print(f"  Granted: {grant.granted_at}")

        if grant.revoked_at is not None:
            print(f"  Revoked: {grant.revoked_at}")

        print()

    return 0
