"""Tests for finding what still uses a project."""

from dataclasses import replace
from pathlib import Path

from aic_control_centre.goals.model import Goal
from aic_control_centre.permissions.model import Grant
from aic_control_centre.projects.registry import Project
from aic_control_centre.projects.removal import removal_blockers


def _project(name="app", parent="one"):
    return Project(name=name, path=Path("/work") / parent / name)


def _goal(project="app"):
    return Goal.create(description="Do something", project=project)


def _grant(project="app", target="inspect", revoked=False):
    grant = Grant.create(project, target, "because")

    if revoked:
        return replace(grant, revoked_at="2026-10-28T00:00:00+00:00")

    return grant


def test_nothing_blocks_a_project_that_nothing_uses() -> None:
    """No goal and no grant means that the entry can go."""
    project = _project()

    blockers = removal_blockers(project, [project], [], [])

    assert blockers.found is False
    assert blockers.goals == ()
    assert blockers.grants == ()


def test_goals_of_the_project_block_it() -> None:
    """Every goal that names the project is reported, in order."""
    project = _project()
    goals = [_goal(), _goal("other"), _goal()]

    blockers = removal_blockers(project, [project], goals, [])

    assert blockers.found is True
    assert blockers.goals == (goals[0], goals[2])
    assert blockers.grants == ()


def test_active_grants_of_the_project_block_it() -> None:
    """A grant for another project does not."""
    project = _project()
    grants = [_grant(), _grant("other"), _grant(target="noop")]

    blockers = removal_blockers(project, [project], [], grants)

    assert blockers.found is True
    assert blockers.grants == (grants[0], grants[2])
    assert blockers.goals == ()


def test_a_revoked_grant_is_history_and_does_not_block() -> None:
    """Only an active grant blocks."""
    project = _project()

    blockers = removal_blockers(
        project,
        [project],
        [],
        [_grant(revoked=True), _grant(target="noop", revoked=True)],
    )

    assert blockers.found is False


def test_the_name_is_matched_exactly() -> None:
    """A name that differs in case is another name."""
    project = _project("app")

    blockers = removal_blockers(
        project,
        [project],
        [_goal("App"), _goal("APP")],
        [_grant("App")],
    )

    assert blockers.found is False


def test_nothing_blocks_when_another_entry_keeps_the_name() -> None:
    """The goals and the grants still name a registered project."""
    first = _project(parent="one")
    second = _project(parent="two")

    blockers = removal_blockers(
        first,
        [first, second],
        [_goal(), _goal()],
        [_grant()],
    )

    assert blockers.found is False


def test_a_different_project_with_goals_does_not_matter() -> None:
    """Only the name of the project that is removed counts."""
    first = _project("app")
    second = _project("lib")

    blockers = removal_blockers(
        first,
        [first, second],
        [_goal("lib")],
        [_grant("lib")],
    )

    assert blockers.found is False


def test_goals_and_grants_are_reported_together() -> None:
    """Both kinds are in one answer."""
    project = _project()

    blockers = removal_blockers(
        project,
        [project],
        [_goal()],
        [_grant()],
    )

    assert len(blockers.goals) == 1
    assert len(blockers.grants) == 1
    assert blockers.found is True
