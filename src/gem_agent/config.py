from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"
PROPOSALS_DIR = OUTPUT_DIR / "proposals"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    gmail_address: str = ""
    gmail_app_password: str = ""

    gem_username: str = ""
    gem_password: str = ""

    autonomy_mode: str = "draft_only"  # draft_only | approve_then_assist

    database_path: Path = Field(default_factory=lambda: DATA_DIR / "agent.db")
    profile_path: Path = Field(default_factory=lambda: CONFIG_DIR / "profile.yaml")
    keywords_path: Path = Field(default_factory=lambda: CONFIG_DIR / "keywords.yaml")


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def load_profile(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return load_yaml(settings.profile_path)


def load_keywords(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return load_yaml(settings.keywords_path)
