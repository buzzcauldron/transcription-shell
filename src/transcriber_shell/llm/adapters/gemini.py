"""Google Gemini — optional extra transcriber-shell[gemini]."""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from unittest.mock import patch

from transcriber_shell.config import Settings
from transcriber_shell.llm.transcribe import TranscribeResult


def _sleep_backoff(attempt: int) -> None:
    base = min(32.0, 2.0**attempt)
    time.sleep(base + random.uniform(0.0, 1.0))


def transcribe_gemini(
    *,
    image_path: Path,
    system: str,
    user_text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> TranscribeResult:
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise RuntimeError(
            "Gemini SDK not installed. Run: pip install 'transcriber-shell[gemini]' "
            "(or pip install google-generativeai)."
        ) from e

    s = settings or Settings()
    if not s.google_api_key:
        raise RuntimeError(
            "No Google API key for Gemini: set GOOGLE_API_KEY or TRANSCRIBER_SHELL_GOOGLE_API_KEY "
            "in .env or paste under Provider keys in the GUI."
        )
    genai.configure(api_key=s.google_api_key)
    raw = image_path.read_bytes()
    suf = image_path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif suf == ".png":
        mime = "image/png"
    else:
        mime = "image/jpeg"

    model_id = model or s.resolved_model("gemini")
    gen_model = genai.GenerativeModel(model_id, system_instruction=system)
    proxy = (s.llm_http_proxy or "").strip()
    env_extra: dict[str, str] = {}
    if s.llm_use_proxy and proxy:
        env_extra["HTTP_PROXY"] = proxy
        env_extra["HTTPS_PROXY"] = proxy

    max_attempts = 1 + max(0, s.gemini_max_retries)
    for attempt in range(max_attempts):
        try:
            with patch.dict(os.environ, env_extra, clear=False):
                r = gen_model.generate_content(
                    [
                        {"mime_type": mime, "data": raw},
                        user_text,
                    ],
                    request_options={"timeout": s.gemini_timeout_seconds},
                )
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
            return TranscribeResult(text, usage)
        except Exception as exc:
            try:
                from google.api_core.exceptions import ResourceExhausted

                if isinstance(exc, ResourceExhausted) and attempt + 1 < max_attempts:
                    _sleep_backoff(attempt)
                    continue
            except ImportError:
                pass
            raise
    raise RuntimeError("Gemini: internal retry loop exited unexpectedly")
