"""Configuration management for AI-Control-Centre."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration for AI-Control-Centre."""

    data_dir: Path
    projects_file: Path
    goals_file: Path
    state_dir: Path
    default_model_provider: str


def get_data_dir() -> Path:
    """Return the platform-specific application data directory."""
    override = os.environ.get("AIC_DATA_DIR")

    if override:
        return Path(override).expanduser()

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")

        if base:
            return Path(base) / "AI-Control-Centre"

        return Path.home() / "AppData" / "Local" / "AI-Control-Centre"

    return Path.home() / ".local" / "share" / "ai-control-centre"


def load_config() -> AppConfig:
    """Load configuration using environment variables and defaults."""
    data_dir = get_data_dir()

    model_provider = os.environ.get(
        "AIC_DEFAULT_MODEL_PROVIDER",
        "local",
    )

    return AppConfig(
        data_dir=data_dir,
        projects_file=data_dir / "projects.json",
        goals_file=data_dir / "goals.json",
        state_dir=data_dir / "state",
        default_model_provider=model_provider,
    )
