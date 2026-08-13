"""Google Gemini — optional extra transcriber-shell[gemini]."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch

from transcriber_shell.config import Settings
from transcriber_shell.llm.transcribe import TranscribeResult

# Free-tier quotas are per model per day. Cycle on 429 instead of retrying the
# same exhausted id. Override with GEMINI_MODEL_CYCLE / TRANSCRIBER_SHELL_GEMINI_MODEL_CYCLE
# (comma-separated).
DEFAULT_GEMINI_MODEL_CYCLE: tuple[str, ...] = (
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-flash-latest",
    "gemini-2.5-flash",
)

_skip_lock = threading.Lock()
_skip_models: set[str] = set()


def _reset_gemini_cycle_for_tests() -> None:
    with _skip_lock:
        _skip_models.clear()


def _cycle_from_env() -> tuple[str, ...]:
    raw = (
        os.environ.get("TRANSCRIBER_SHELL_GEMINI_MODEL_CYCLE")
        or os.environ.get("GEMINI_MODEL_CYCLE")
        or ""
    ).strip()
    if not raw:
        return DEFAULT_GEMINI_MODEL_CYCLE
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts or DEFAULT_GEMINI_MODEL_CYCLE


def models_to_try(preferred: str) -> list[str]:
    ordered: list[str] = []
    for mid in (preferred, *_cycle_from_env()):
        if mid and mid not in ordered:
            ordered.append(mid)
    with _skip_lock:
        skipped = set(_skip_models)
    live = [m for m in ordered if m not in skipped]
    return live or ordered


def _mark_skip(model: str) -> None:
    with _skip_lock:
        _skip_models.add(model)


def _is_cycleable_error(exc: BaseException) -> bool:
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(exc, "code", None)
    try:
        icode = int(code) if code is not None else 0
    except (TypeError, ValueError):
        icode = 0
    if icode in {429, 404}:
        return True
    text = str(exc)
    return any(
        tok in text
        for tok in (
            "429",
            "RESOURCE_EXHAUSTED",
            "NOT_FOUND",
            "is not found",
            "not supported",
        )
    )


def transcribe_gemini(
    *,
    image_path: Path | None,
    system: str,
    user_text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> TranscribeResult:
    try:
        import google.genai as genai
        from google.genai import types as genai_types
    except ImportError as e:
        raise RuntimeError(
            "Gemini SDK not installed. Run: pip install 'transcriber-shell[gemini]' "
            "(or pip install google-genai)."
        ) from e

    s = settings or Settings()
    if not s.google_api_key:
        raise RuntimeError(
            "No Google API key for Gemini: set GOOGLE_API_KEY or TRANSCRIBER_SHELL_GOOGLE_API_KEY "
            "in .env or paste under Provider keys in the GUI."
        )
    client = genai.Client(api_key=s.google_api_key)
    from transcriber_shell.protocol_paths import ensure_prompt_builder_on_path

    ensure_prompt_builder_on_path(s)
    from provider_adapters import augment_system_for_provider  # noqa: E402

    system = augment_system_for_provider(system, "gemini")
    preferred = (model or s.resolved_model("gemini")).strip()
    proxy = (s.llm_http_proxy or "").strip()
    env_extra: dict[str, str] = {}
    if s.llm_use_proxy and proxy:
        env_extra["HTTP_PROXY"] = proxy
        env_extra["HTTPS_PROXY"] = proxy

    if image_path is not None:
        from transcriber_shell.llm.image_prep import prepare_image
        raw, mime = prepare_image(image_path)
        contents = [genai_types.Part.from_bytes(data=raw, mime_type=mime), user_text]
    else:
        contents = [user_text]

    last_err: BaseException | None = None
    tried: list[str] = []
    for model_id in models_to_try(preferred):
        tried.append(model_id)
        generate_kwargs: dict = {
            "model": model_id,
            "contents": contents,
            "config": genai_types.GenerateContentConfig(
                system_instruction=system,
                http_options=genai_types.HttpOptions(timeout=s.gemini_timeout_seconds * 1000),
            ),
        }
        try:
            with patch.dict(os.environ, env_extra, clear=False):
                r = client.models.generate_content(**generate_kwargs)
            text = (r.text or "").strip()
            usage: dict[str, int] | None = None
            um = getattr(r, "usage_metadata", None)
            if um is not None:
                pt = getattr(um, "prompt_token_count", None)
                ct = getattr(um, "candidates_token_count", None)
                tt = getattr(um, "total_token_count", None)
                usage = {}
                if pt is not None:
                    usage["input_tokens"] = int(pt)
                if ct is not None:
                    usage["output_tokens"] = int(ct)
                if tt is not None:
                    usage["total_tokens"] = int(tt)
                elif pt is not None and ct is not None:
                    usage["total_tokens"] = int(pt) + int(ct)
                if not usage:
                    usage = None
            if model_id != preferred:
                print(f"[gemini] using {model_id} (cycled off {preferred})", file=sys.stderr, flush=True)
            return TranscribeResult(text, usage)
        except Exception as exc:
            last_err = exc
            if _is_cycleable_error(exc):
                _mark_skip(model_id)
                print(
                    f"[gemini] skip {model_id} ({type(exc).__name__}); trying next model",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            raise
    raise RuntimeError(
        "Gemini: all models in cycle exhausted or unavailable "
        f"(tried {', '.join(tried) or preferred}). Last error: {last_err}"
    )
