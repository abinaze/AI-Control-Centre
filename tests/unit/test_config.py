from pathlib import Path

from aic_control_centre.config import get_data_dir, load_config


def test_default_config_uses_local_model_provider(monkeypatch):
    monkeypatch.delenv("AIC_DEFAULT_MODEL_PROVIDER", raising=False)

    config = load_config()

    assert config.default_model_provider == "local"


def test_model_provider_can_be_overridden(monkeypatch):
    monkeypatch.setenv("AIC_DEFAULT_MODEL_PROVIDER", "test-provider")

    config = load_config()

    assert config.default_model_provider == "test-provider"


def test_data_directory_can_be_overridden(monkeypatch, tmp_path):
    custom_dir = tmp_path / "aic-data"

    monkeypatch.setenv("AIC_DATA_DIR", str(custom_dir))

    assert get_data_dir() == custom_dir


def test_config_paths_are_inside_data_directory(monkeypatch, tmp_path):
    custom_dir = tmp_path / "aic-data"

    monkeypatch.setenv("AIC_DATA_DIR", str(custom_dir))

    config = load_config()

    assert config.data_dir == custom_dir
    assert config.projects_file == custom_dir / "projects.json"
    assert config.state_dir == custom_dir / "state"


def test_config_paths_are_path_objects():
    config = load_config()

    assert isinstance(config.data_dir, Path)
    assert isinstance(config.projects_file, Path)
    assert isinstance(config.state_dir, Path)
