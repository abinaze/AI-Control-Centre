"""Projects that an execution request may name.

A target that acts on the files of a project must be given the directory
of the project that the task belongs to. Admission asks a project source
for it, and a source that has no projects finds nothing, so by default no
project is usable.
"""

from __future__ import annotations

from typing import Protocol

from aic_control_centre.projects.registry import Project


class ProjectSource(Protocol):
    """Anything that can find a registered project by its name."""

    def get_project(self, name: str) -> Project | None:
        """Return the registered project with this exact name, if any."""


class NoProjects:
    """A project source with no projects, so every lookup finds nothing."""

    def get_project(self, name: str) -> Project | None:
        """Return None for every name."""
        return None
