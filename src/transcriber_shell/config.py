"""Runtime configuration (env + optional .env)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    protocol_root: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_PROTOCOL_ROOT",
            "PROTOCOL_ROOT",
        ),
        description="Path to transcription-protocol checkout.",
    )
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ANTHROPIC_API_KEY", "TRANSCRIBER_SHELL_ANTHROPIC_API_KEY"),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "TRANSCRIBER_SHELL_OPENAI_API_KEY"),
    )
    google_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_API_KEY", "TRANSCRIBER_SHELL_GOOGLE_API_KEY"),
    )

    anthropic_model: str = Field(
        default="claude-sonnet-4-20250514",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_ANTHROPIC_MODEL", "ANTHROPIC_MODEL"
        ),
    )
    openai_model: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_OPENAI_MODEL", "OPENAI_MODEL"),
    )
    gemini_model: str = Field(
        default="gemini-2.0-flash",
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_GEMINI_MODEL", "GEMINI_MODEL"),
    )

    gm_headless: bool = Field(
        default=True,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_GM_HEADLESS", "GM_HEADLESS"),
    )
    gm_timeout_ms: int = Field(
        default=120_000,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_GM_TIMEOUT_MS", "GM_TIMEOUT_MS"),
    )
    gm_base_url: str = Field(
        default="https://glyphmachina.com/",
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_GM_BASE_URL", "GM_BASE_URL"),
    )

    artifacts_dir: Path = Field(
        default=Path("artifacts"),
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_ARTIFACTS_DIR", "ARTIFACTS_DIR"),
    )

    def resolved_protocol_root(self, package_root: Path | None = None) -> Path:
        if self.protocol_root is not None:
            return self.protocol_root.expanduser().resolve()
        base = package_root or Path(__file__).resolve().parents[2]
        return (base / "vendor" / "transcription-protocol").resolve()


ProviderName = Literal["anthropic", "openai", "gemini"]
