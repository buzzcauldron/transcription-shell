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
    ollama_timeout_seconds: float = Field(
        default=3_600.0,
        ge=30.0,
        le=21_600.0,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_OLLAMA_TIMEOUT_S",
            "TRANSCRIBER_SHELL_OLLAMA_TIMEOUT",
        ),
        description="HTTP timeout (seconds) for Ollama /api/chat; local vision models are often slow on CPU.",
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

    openai_timeout_seconds: float = Field(
        default=600.0,
        ge=30.0,
        le=3_600.0,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_OPENAI_TIMEOUT_S"),
        description="HTTP timeout (seconds) for OpenAI API calls.",
    )
    openai_max_retries: int = Field(
        default=2,
        ge=0,
        le=8,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_OPENAI_MAX_RETRIES"),
        description="Extra attempts after the first for 429/503 (rate limit / service unavailable).",
    )

    gemini_timeout_seconds: float = Field(
        default=600.0,
        ge=30.0,
        le=3_600.0,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_GEMINI_TIMEOUT_S"),
        description="Request timeout (seconds) for Gemini generate_content calls.",
    )
    gemini_max_retries: int = Field(
        default=1,
        ge=0,
        le=8,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_GEMINI_MAX_RETRIES"),
        description="Extra attempts after the first for ResourceExhausted (quota/rate-limit).",
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
        default=600_000,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_GM_TIMEOUT_MS", "GM_TIMEOUT_MS"),
        description=(
            "Overall Glyph Machina session budget (ms). Default 10 minutes. "
            "gm_navigate_timeout_ms + gm_identify_timeout_ms should not exceed this."
        ),
    )
    gm_navigate_timeout_ms: int = Field(
        default=60_000,
        ge=5_000,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_GM_NAVIGATE_TIMEOUT_MS",
            "GM_NAVIGATE_TIMEOUT_MS",
        ),
        description=(
            "Playwright timeout for navigation + file-input phases (goto, wait_for, button click). "
            "Default 60 seconds. Increase on very slow networks."
        ),
    )
    gm_identify_timeout_ms: int = Field(
        default=540_000,
        ge=30_000,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_GM_IDENTIFY_TIMEOUT_MS",
            "GM_IDENTIFY_TIMEOUT_MS",
        ),
        description=(
            "Playwright timeout for the Identify Lines + download phases. "
            "Default 9 minutes. Increase for slow or complex manuscripts."
        ),
    )
    gm_base_url: str = Field(
        default="https://glyphmachina.com/",
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_GM_BASE_URL", "GM_BASE_URL"),
    )
    gm_post_identify_wait_ms: int = Field(
        default=5_000,
        ge=0,
        le=600_000,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_GM_POST_IDENTIFY_WAIT_MS",
            "GM_POST_IDENTIFY_WAIT_MS",
        ),
        description=(
            "Initial grace period (ms) after clicking Identify Lines before _wait_for_download_control "
            "polling begins — not the total wait for detection. Default 5 seconds; "
            "the polling loop handles the rest up to gm_identify_timeout_ms."
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
    gm_auto_install_browser: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_GM_AUTO_INSTALL_BROWSER",
        ),
        description=(
            "If true, run `python -m playwright install chromium` once per process before the first "
            "Playwright session (idempotent when Chromium is already installed; set false for air-gapped hosts)."
        ),
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
        default="auto",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_KRAKEN_DEVICE", "KRAKEN_DEVICE"
        ),
        description=(
            "Torch device for kraken inference. 'auto' (default) picks MPS on Apple "
            "Silicon, CUDA when available, else CPU. Explicit 'cpu'/'mps'/'cuda:N' override."
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

    # HTR backends (optional; run in parallel alongside LLM)
    kraken_htr_model_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH", "KRAKEN_HTR_MODEL_PATH"
        ),
        description=(
            "Path to a kraken .mlmodel for HTR (e.g. Zenodo HTR_medieval_documentary_best.mlmodel). "
            "Credit: Pinche, Camps, Ing (2023) https://doi.org/10.5281/zenodo.7547438 CC BY 4.0"
        ),
    )
    gm_htr_repo_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_GM_HTR_REPO_PATH", "GM_HTR_REPO_PATH"
        ),
        description=(
            "Path to a clone of ideasrule/glyph_machina_public (GPL-3.0). "
            "Used for both local segmentation (seg.mlmodel replaces Playwright website call) "
            "and HTR (run_line_image_generator.py + run_htr.py alongside the LLM). "
            "Credit: ideasrule/glyph_machina_public; training data: mzzhang2014/glyph_machina (HuggingFace)"
        ),
    )
    gm_website_fallback: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_GM_WEBSITE_FALLBACK", "GM_WEBSITE_FALLBACK"
        ),
        description=(
            "When gm_htr_repo_path is set and the local segmentation fails, fall back to the "
            "Playwright website call. Set false to disable the website call entirely."
        ),
    )
    reuse_lines_xml: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_REUSE_LINES_XML",
            "REUSE_LINES_XML",
        ),
        description=(
            "If an artifacts/<job_id>/lines.xml file already exists and is non-empty, "
            "reuse it and skip the lineation step. Saves the ~8 s/page lineation cost "
            "when retrying a batch where the LLM call previously failed. Set to false "
            "to force re-lineation."
        ),
    )

    batch_parallel_pages: int = Field(
        default=3,
        ge=1,
        le=16,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_BATCH_PARALLEL_PAGES",
            "BATCH_PARALLEL_PAGES",
        ),
        description=(
            "Number of pages run concurrently in run_batch. Pages are independent, "
            "so a small thread pool (3 by default) overlaps LLM I/O wait with the next "
            "page's lineation. Set to 1 to force serial execution."
        ),
    )

    pdf_dpi: int = Field(
        default=300,
        ge=72,
        le=600,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_PDF_DPI", "PDF_DPI"
        ),
        description=(
            "Rasterisation DPI when expanding PDFs to per-page JPGs (pipeline/pdf_extract). "
            "300 is the safe default; drop to 200 for ~2× faster rasterisation when the "
            "HTR backend doesn't need ultra-fine glyph detail."
        ),
    )

    figure_extract_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_FIGURE_EXTRACT_ENABLED",
            "FIGURE_EXTRACT_ENABLED",
        ),
        description=(
            "If true, run figure detection on each page after transcription, save per-figure "
            "PNG crops under artifacts/<job_id>/figures/, and weave [fig:id] markers into "
            "the transcription YAML. Install: pip install 'transcriber-shell[figures]'."
        ),
    )
    figure_extract_backend: str = Field(
        default="doclaynet",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_FIGURE_EXTRACT_BACKEND",
            "FIGURE_EXTRACT_BACKEND",
        ),
        description="Figure-detection backend. Currently: doclaynet (DocLayNet YOLO via HF Hub).",
    )
    figure_extract_model: str = Field(
        default="juliozhao/DocLayout-YOLO-DocLayNet",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_FIGURE_EXTRACT_MODEL",
            "FIGURE_EXTRACT_MODEL",
        ),
        description="HF Hub repo id or local .pt path for the layout YOLO model.",
    )
    figure_min_confidence: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_FIGURE_MIN_CONFIDENCE",
            "FIGURE_MIN_CONFIDENCE",
        ),
        description="Drop detections below this YOLO confidence (0–1).",
    )
    figure_min_area_frac: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_FIGURE_MIN_AREA_FRAC",
            "FIGURE_MIN_AREA_FRAC",
        ),
        description="Drop detections smaller than this fraction of the full page area.",
    )
    figure_pad_px: int = Field(
        default=8,
        ge=0,
        le=200,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_FIGURE_PAD_PX",
            "FIGURE_PAD_PX",
        ),
        description="Pixels of padding added on each side when cropping the page image.",
    )
    figure_classes: str = Field(
        default="Picture,Table",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_FIGURE_CLASSES",
            "FIGURE_CLASSES",
        ),
        description=(
            "Comma-separated DocLayNet class names that count as 'figures' "
            "(e.g. 'Picture,Table,Caption'). Default: 'Picture,Table'. "
            "Use ``settings.figure_classes_list`` for the parsed list form."
        ),
    )

    tesseract_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_TESSERACT_ENABLED", "TESSERACT_ENABLED"
        ),
        description=(
            "Enable the Tesseract HTR backend (early modern print). Needs a system tesseract "
            "binary and traineddata files for the configured languages. "
            "Install: pip install 'transcriber-shell[tesseract]'."
        ),
    )
    tesseract_lang: str = Field(
        default="lat+frk+eng",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_TESSERACT_LANG", "TESSERACT_LANG"
        ),
        description=(
            "Tesseract language stack for early modern print. Defaults to lat+frk+eng "
            "(Latin + Fraktur + English); use deu_latf+frk for German Fraktur, ita+lat for "
            "Italian humanist print, etc."
        ),
    )
    tesseract_psm: int = Field(
        default=7,
        ge=0,
        le=13,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_TESSERACT_PSM", "TESSERACT_PSM"
        ),
        description="Page Segmentation Mode. 7 = single line (recommended when we crop per TextLine).",
    )

    htr_parallel: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_HTR_PARALLEL", "HTR_PARALLEL"
        ),
        description=(
            "If true, run kraken-htr / gm-htr in parallel with the LLM. "
            "If false, run HTR first (after lineation), append drafts to the lineation hint, then call the LLM "
            "(lineation → HTR → LLM). Ignored when htr_combination is not default."
        ),
    )
    htr_combination: str = Field(
        default="default",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_HTR_COMBINATION",
            "HTR_COMBINATION",
        ),
        description=(
            "Combine Glyph Machina HTR (best), Zenodo kraken-htr (second), and LLM-only shell: "
            "default (follow htr_parallel), shell (original shell: LLM only, no HTR), off, "
            "kraken_htr, gm_htr, parallel (all HTR with LLM), sequential (all HTR then LLM), "
            "gm_then_kraken, kraken_then_gm, htr_only (all HTR, no LLM), "
            "gm_htr_only (GM only, no LLM), kraken_htr_only (Kraken only, no LLM). "
            "Aliases: zenodo→kraken_htr, glyph_machina|gm→gm_htr, none|llm_only→shell|off."
        ),
    )

    llm_mode: str = Field(
        default="full",
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_LLM_MODE",
            "LLM_MODE",
        ),
        description=(
            "LLM stage behavior. full (current default — protocol YAML); "
            "correct (short prompt: treat HTR draft as primary, fix recognition errors); "
            "off (skip LLM entirely — equivalent to setting htr_combination to a *_only variant). "
            "Honored only when an HTR backend produced drafts; falls back to full otherwise."
        ),
    )

    artifacts_dir: Path = Field(
        default=Path(__file__).resolve().parents[2] / "artifacts",
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
    skip_lines_xml_validation: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_SKIP_LINES_XML_VALIDATION",
        ),
        description="If true, skip lines XML checks and optional PAGE XSD; still run LLM (CLI: --skip-lines-xml-validation).",
    )
    continue_on_lineation_failure: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "TRANSCRIBER_SHELL_CONTINUE_ON_LINEATION_FAILURE",
        ),
        description=(
            "If true, when automated lineation fails (Glyph Machina, mask, Kraken, timeouts), "
            "continue to LLM transcription without lines XML instead of failing the run (CLI: --continue-on-lineation-failure)."
        ),
    )
    xml_only: bool = Field(
        default=False,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_XML_ONLY"),
        description=(
            "If true, run lineation and lines XML validation only; do not call the LLM (CLI: --xml-only)."
        ),
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

    # Document-type system (replaces best_model.sh)
    doc_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_DOC_TYPE", "LATIN_MS_DOC_TYPE"),
        description="Document type name (e.g. medieval_latin_legal). Loads matching spec YAML.",
    )
    document_types_dir: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_DOCUMENT_TYPES_DIR"),
        description="Extra directory to search for <doc_type>.yaml specs.",
    )

    # Illustration masking (eynollah)
    mask_illustrations: bool = Field(
        default=False,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_MASK_ILLUSTRATIONS"),
        description="If true, white out eynollah class-2 (illustration) pixels before lineation.",
    )
    eynollah_model_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_EYNOLLAH_MODEL"),
        description="Path to eynollah SBB SavedModel directory.",
    )
    mask_dilate_px: int = Field(
        default=8,
        ge=0,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_MASK_DILATE"),
        description="Dilation radius in pixels applied to the illustration mask.",
    )

    # Ground-truth directory for scoring
    gt_dir: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("TRANSCRIBER_SHELL_GT_DIR", "LATIN_MS_GT_DIR"),
        description="Directory of ground-truth PAGE XML files for transcriber-shell score.",
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

    @field_validator("figure_classes", mode="before")
    @classmethod
    def _normalize_figure_classes(cls, v: object) -> str:
        if v is None or v == "":
            return "Picture,Table"
        if isinstance(v, (list, tuple)):
            return ",".join(str(x).strip() for x in v if str(x).strip())
        if isinstance(v, str):
            parts = [x.strip() for x in v.split(",") if x.strip()]
            return ",".join(parts) if parts else "Picture,Table"
        return str(v)

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
            return "glyph_machina"
        if not isinstance(v, str):
            raise ValueError("lineation_backend must be a string")
        x = v.lower().strip()
        if x not in allowed:
            raise ValueError(f"lineation_backend must be one of {allowed}")
        return x

    @field_validator("htr_combination", mode="before")
    @classmethod
    def _normalize_htr_combination(cls, v: object) -> str:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return "default"
        if not isinstance(v, str):
            raise ValueError("htr_combination must be a string")
        s = v.strip().lower()
        aliases = {
            "none": "off",
            "llm_only": "shell",
            "zenodo": "kraken_htr",
            "glyph_machina": "gm_htr",
            "gm": "gm_htr",
            "tesseract": "tesseract_htr",
            "early_modern": "tesseract_htr",
            "gm_then_zenodo": "gm_then_kraken",
            "best_then_second": "gm_then_kraken",
            "zenodo_then_gm": "kraken_then_gm",
            "second_then_best": "kraken_then_gm",
        }
        s = aliases.get(s, s)
        allowed = frozenset(
            {
                "default",
                "off",
                "shell",
                "kraken_htr",
                "gm_htr",
                "tesseract_htr",
                "parallel",
                "sequential",
                "gm_then_kraken",
                "kraken_then_gm",
                "htr_only",
                "gm_htr_only",
                "kraken_htr_only",
            }
        )
        if s not in allowed:
            raise ValueError(
                f"htr_combination must be one of {sorted(allowed)}; got {s!r}"
            )
        return s

    @property
    def figure_classes_list(self) -> list[str]:
        """``figure_classes`` parsed into a list of trimmed class names."""
        return [x.strip() for x in self.figure_classes.split(",") if x.strip()]

    @field_validator("llm_mode", mode="before")
    @classmethod
    def _normalize_llm_mode(cls, v: object) -> str:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return "full"
        if not isinstance(v, str):
            raise ValueError("llm_mode must be a string")
        s = v.strip().lower()
        aliases = {"normal": "full", "default": "full", "skip": "off", "none": "off"}
        s = aliases.get(s, s)
        allowed = {"full", "correct", "off"}
        if s not in allowed:
            raise ValueError(f"llm_mode must be one of {sorted(allowed)}; got {s!r}")
        return s

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
