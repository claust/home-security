from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_archive_path() -> Path:
    return Path.home() / ".local/state/home-security/archive.sqlite3"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HOME_SECURITY_API_",
        env_file=None,
        extra="ignore",
        frozen=True,
    )

    archive_path: Path = Field(default_factory=_default_archive_path)
    host: str = "127.0.0.1"
    port: int = Field(default=8002, ge=1, le=65535)
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value
