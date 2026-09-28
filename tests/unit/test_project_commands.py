from pathlib import Path

from aic_control_centre.projects.commands import add_project, list_projects
from aic_control_centre.projects.registry import ProjectRegistry


def test_add_project_command_registers_project(tmp_path, monkeypatch, capsys):
    project_path = tmp_path / "example-project"
    project_path.mkdir()

    registry_path = tmp_path / "projects.json"
    monkeypatch.setenv("AIC_DATA_DIR", str(tmp_path))

    result = add_project(str(project_path))

    assert result == 0

    output = capsys.readouterr().out

    assert "Project registered: example-project" in output

    registry = ProjectRegistry(registry_path)

    assert len(registry.list_projects()) == 1


def test_add_project_command_rejects_missing_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AIC_DATA_DIR", str(tmp_path))

    result = add_project(str(tmp_path / "missing-project"))

    assert result == 1

    output = capsys.readouterr().out

    assert "does not exist" in output


def test_list_projects_command_handles_empty_registry(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("AIC_DATA_DIR", str(tmp_path))

    result = list_projects()

    assert result == 0

    output = capsys.readouterr().out

    assert "No projects registered." in output
