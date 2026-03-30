"""Runtime configuration (env + optional .env)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["anthropic", "openai", "gemini"]


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

    default_provider: ProviderName = Field(
        default="anthropic",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_DEFAULT_PROVIDER", "DEFAULT_PROVIDER"
        ),
    )
    # When set, overrides anthropic_model / openai_model / gemini_model for the active provider.
    default_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_MODEL", "DEFAULT_MODEL"),
    )

    api_host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_API_HOST", "API_HOST"),
    )
    api_port: int = Field(
        default=8765,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_API_PORT", "API_PORT"),
    )
    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_API_KEY", "API_KEY"),
    )

    @field_validator("default_provider", mode="before")
    @classmethod
    def _normalize_default_provider(cls, v: object) -> str:
        allowed = ("anthropic", "openai", "gemini")
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return "anthropic"
        if not isinstance(v, str):
            raise ValueError("default_provider must be a string")
        x = v.lower().strip()
        if x not in allowed:
            raise ValueError(f"default_provider must be one of {allowed}")
        return x

    def resolved_protocol_root(self, package_root: Path | None = None) -> Path:
        if self.protocol_root is not None:
            return self.protocol_root.expanduser().resolve()
        base = package_root or Path(__file__).resolve().parents[2]
        return (base / "vendor" / "transcription-protocol").resolve()

    def resolved_model(self, provider: str) -> str:
        """Model id for API calls. Precedence: default_model (env) > per-provider default."""
        if self.default_model:
            return self.default_model
        p = provider.lower()
        if p == "anthropic":
            return self.anthropic_model
        if p == "openai":
            return self.openai_model
        if p == "gemini":
            return self.gemini_model
        return self.anthropic_model
