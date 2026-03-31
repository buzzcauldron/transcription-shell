"""Runtime configuration (env + optional .env)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["anthropic", "openai", "gemini", "ollama"]
LineationBackend = Literal["mask", "kraken", "glyph_machina"]


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
    ollama_model: str = Field(
        default="llava",
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_OLLAMA_MODEL", "OLLAMA_MODEL"),
    )
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_OLLAMA_BASE_URL", "OLLAMA_BASE_URL"
        ),
    )

    anthropic_timeout_seconds: float = Field(
        default=600.0,
        ge=30.0,
        le=3_600.0,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_ANTHROPIC_TIMEOUT_S",
            "TRANSCRIBER_SHELL_ANTHROPIC_TIMEOUT",
        ),
        description="HTTP timeout (seconds) for Anthropic API calls; vision+YAML can be slow.",
    )
    anthropic_max_retries: int = Field(
        default=2,
        ge=0,
        le=8,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_ANTHROPIC_MAX_RETRIES"),
        description="Extra attempts after the first for 429/503/529 (rate limit / overloaded).",
    )

    llm_use_proxy: bool = Field(
        default=False,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_LLM_USE_PROXY"),
        description="Route Anthropic/OpenAI HTTP via llm_http_proxy (Gemini uses HTTP(S)_PROXY for the call).",
    )
    llm_http_proxy: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_LLM_HTTP_PROXY",
            "TRANSCRIBER_SHELL_HTTPS_PROXY",
        ),
        description="Proxy URL for cloud LLM clients (e.g. http://user:pass@host:8080).",
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
    gm_post_identify_wait_ms: int = Field(
        default=2_000,
        ge=0,
        le=600_000,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_GM_POST_IDENTIFY_WAIT_MS",
            "GM_POST_IDENTIFY_WAIT_MS",
        ),
        description=(
            "Pause after Identify Lines before waiting on the download control — gives the SPA time "
            "to run line detection before #downloadLinesBtn becomes actionable."
        ),
    )
    gm_persistent_profile: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_GM_PERSISTENT_PROFILE",
            "TRANSCRIBER_SHELL_GM_USE_PERSISTENT_PROFILE",
        ),
        description="Use a stable Chromium profile dir so Glyph Machina logins persist.",
    )
    gm_user_data_dir: Path = Field(
        default_factory=lambda: Path.home()
        / ".cache"
        / "transcriber-shell"
        / "glyph-machina-browser",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_GM_USER_DATA_DIR",
            "TRANSCRIBER_SHELL_GM_BROWSER_PROFILE",
        ),
        description="Playwright persistent context directory (cookies, local site data).",
    )

    lineation_backend: LineationBackend = Field(
        default="glyph_machina",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_LINEATION_BACKEND", "LINEATION_BACKEND"
        ),
        description="glyph_machina: browser; mask: local masks→PageXML; kraken: Kraken BLLA",
    )
    lineation_credit_repo_url: str = Field(
        default="https://github.com/ideasrule/latin_documents",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_LINEATION_CREDIT_REPO_URL",
            "LINEATION_CREDIT_REPO_URL",
        ),
    )
    # Mask backend: set mask_inference_callable (module:func) and/or mask_pred_npy_path.
    mask_inference_callable: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE",
            "MASK_INFERENCE_CALLABLE",
        ),
        description="Import path 'pkg.mod:predict' returning (N,H,W) float masks",
    )
    mask_pred_npy_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_MASK_PRED_NPY_PATH",
            "MASK_PRED_NPY_PATH",
        ),
        description="Path to pred .npy; may include {stem} {job_id}",
    )
    mask_device: str = Field(
        default="cpu",
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_MASK_DEVICE", "MASK_DEVICE"),
    )
    mask_threshold: float = Field(
        default=0.5,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_MASK_THRESHOLD", "MASK_THRESHOLD"
        ),
    )
    mask_channel_min_mass: float = Field(
        default=15.0,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_MASK_CHANNEL_MIN_MASS",
            "MASK_CHANNEL_MIN_MASS",
        ),
        description=(
            "latin_lineation_mvp.infer: min sum(sigmoid) per channel to keep a line mask "
            "(lower = more lines, noisier)."
        ),
    )
    mask_channel_min_peak: float = Field(
        default=0.12,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_MASK_CHANNEL_MIN_PEAK",
            "MASK_CHANNEL_MIN_PEAK",
        ),
        description="latin_lineation_mvp.infer: keep channel if max(sigmoid) >= this.",
    )
    mask_max_output_lines: int = Field(
        default=96,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_MASK_MAX_OUTPUT_LINES",
            "MASK_MAX_OUTPUT_LINES",
        ),
        description="latin_lineation_mvp.infer: cap line count after filtering.",
    )
    mask_weights_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH",
            "MASK_WEIGHTS_PATH",
        ),
        description="Optional checkpoint path for mask inference plugins (read in your callable).",
    )
    mask_reference_xml_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_MASK_REFERENCE_XML_PATH",
            "MASK_REFERENCE_XML_PATH",
        ),
        description=(
            "Optional Glyph Machina (or other) reference PageXML path; {stem}/{job_id}. "
            "After mask lineation, baselines are replaced to match reference when set."
        ),
    )
    mask_gm_centroid_match_px: float = Field(
        default=120.0,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_MASK_GM_CENTROID_MATCH_PX",
            "MASK_GM_CENTROID_MATCH_PX",
        ),
        description="Centroid distance for matching local lines to reference when applying GM corrections.",
    )
    mask_baseline_smooth_window: int = Field(
        default=5,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_MASK_BASELINE_SMOOTH_WINDOW",
            "MASK_BASELINE_SMOOTH_WINDOW",
        ),
        description="Moving-average window for column-median baselines (0 = off).",
    )
    kraken_model_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH", "KRAKEN_MODEL_PATH"
        ),
    )
    kraken_device: str = Field(
        default="cpu",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_KRAKEN_DEVICE", "KRAKEN_DEVICE"
        ),
    )
    kraken_threshold: float = Field(
        default=0.10,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_KRAKEN_THRESHOLD", "KRAKEN_THRESHOLD"
        ),
    )
    kraken_min_length: float = Field(
        default=100.0,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_KRAKEN_MIN_LENGTH", "KRAKEN_MIN_LENGTH"
        ),
    )

    artifacts_dir: Path = Field(
        default=Path("artifacts"),
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_ARTIFACTS_DIR", "ARTIFACTS_DIR"),
    )

    # Lines XML gate (optional PAGE XSD; TextLine requirement). CLI flags override env.
    lines_xml_xsd: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_LINES_XML_XSD",
            "TRANSCRIBER_SHELL_PAGE_XSD",
        ),
        description="Optional PAGE XML XSD path for lines file validation (needs [xml-xsd]).",
    )
    xml_require_text_line: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_XML_REQUIRE_TEXT_LINE",
        ),
        description="If false, lines XML may have zero TextLine elements (CLI: --no-require-text-line).",
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

    @field_validator("lines_xml_xsd", mode="before")
    @classmethod
    def _empty_lines_xml_xsd_none(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return None
        if isinstance(v, str):
            return Path(v).expanduser()
        if isinstance(v, Path):
            return v.expanduser()
        return v

    @field_validator("llm_http_proxy", mode="before")
    @classmethod
    def _empty_llm_http_proxy_none(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return None
        return v

    @field_validator("gm_user_data_dir", mode="before")
    @classmethod
    def _expand_gm_user_data_dir(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return Path.home() / ".cache" / "transcriber-shell" / "glyph-machina-browser"
        if isinstance(v, str):
            return Path(v).expanduser()
        if isinstance(v, Path):
            return v.expanduser()
        return v

    @field_validator("default_provider", mode="before")
    @classmethod
    def _normalize_default_provider(cls, v: object) -> str:
        allowed = ("anthropic", "openai", "gemini", "ollama")
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return "anthropic"
        if not isinstance(v, str):
            raise ValueError("default_provider must be a string")
        x = v.lower().strip()
        if x not in allowed:
            raise ValueError(f"default_provider must be one of {allowed}")
        return x

    @field_validator("lineation_backend", mode="before")
    @classmethod
    def _normalize_lineation_backend(cls, v: object) -> str:
        allowed = ("mask", "kraken", "glyph_machina")
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return "mask"
        if not isinstance(v, str):
            raise ValueError("lineation_backend must be a string")
        x = v.lower().strip()
        if x not in allowed:
            raise ValueError(f"lineation_backend must be one of {allowed}")
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
        if p == "ollama":
            return self.ollama_model
        return self.anthropic_model
