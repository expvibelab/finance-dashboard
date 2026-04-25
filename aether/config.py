"""Centralised configuration loaded from environment variables and .env."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    model: str = Field(default="claude-opus-4-7", alias="AETHER_MODEL")
    fast_model: str = Field(
        default="claude-haiku-4-5-20251001", alias="AETHER_FAST_MODEL"
    )

    home: Path = Field(default=Path("./data"), alias="AETHER_HOME")
    db_path: Path = Field(default=Path("./data/state.db"), alias="AETHER_DB_PATH")
    log_level: str = Field(default="INFO", alias="AETHER_LOG_LEVEL")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_users: str = Field(default="", alias="TELEGRAM_ALLOWED_USERS")

    discord_bot_token: str = Field(default="", alias="DISCORD_BOT_TOKEN")
    discord_allowed_users: str = Field(default="", alias="DISCORD_ALLOWED_USERS")

    evolve_enabled: bool = Field(default=True, alias="AETHER_EVOLVE_ENABLED")
    evolve_min_uses: int = Field(default=5, alias="AETHER_EVOLVE_MIN_USES")

    memory_nudge_interval: int = Field(default=20, alias="AETHER_MEMORY_NUDGE_INTERVAL")
    summarize_after: int = Field(default=40, alias="AETHER_SUMMARIZE_AFTER")

    personality: str = Field(default="default", alias="AETHER_PERSONALITY")
    max_turns: int = Field(default=200, alias="AETHER_MAX_TURNS")

    permission_mode: Literal[
        "default", "acceptEdits", "dontAsk", "bypassPermissions"
    ] = Field(default="acceptEdits", alias="AETHER_PERMISSION_MODE")

    @property
    def allowed_telegram_users(self) -> set[int]:
        if not self.telegram_allowed_users.strip():
            return set()
        return {int(x.strip()) for x in self.telegram_allowed_users.split(",") if x.strip()}

    @property
    def allowed_discord_users(self) -> set[int]:
        if not self.discord_allowed_users.strip():
            return set()
        return {int(x.strip()) for x in self.discord_allowed_users.split(",") if x.strip()}

    def ensure_dirs(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings
