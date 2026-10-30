"""Find what still uses a project before it is removed."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from aic_control_centre.goals.model import Goal
from aic_control_centre.permissions.model import Grant
from aic_control_centre.projects.registry import Project


@dataclass(frozen=True)
class Blockers:
    """The goals and the active grants that name a project."""

    goals: tuple[Goal, ...] = ()
    grants: tuple[Grant, ...] = ()

    @property
    def found(self) -> bool:
        """Return whether anything blocks the removal."""
        return bool(self.goals or self.grants)


def removal_blockers(
    project: Project,
    projects: Iterable[Project],
    goals: Iterable[Goal],
    grants: Iterable[Grant],
) -> Blockers:
    """Return what the removal of a registry entry would leave dangling.

    Goals and grants identify a project by its name. Removing an entry
    leaves them pointing at a name that is no longer registered, unless
    another entry keeps the name, as when a registry holds one name twice.
    A revoked grant is history and does not block. A name that belongs to
    a different project in case only is a different name.
    """
    if sum(1 for item in projects if item.name == project.name) > 1:
        return Blockers()

    return Blockers(
        goals=tuple(goal for goal in goals if goal.project == project.name),
        grants=tuple(
            grant
            for grant in grants
            if grant.project == project.name and grant.is_active
        ),
    )
