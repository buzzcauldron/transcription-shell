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
    raw = image_path.read_bytes()
    suf = image_path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif suf == ".png":
        mime = "image/png"
    else:
        mime = "image/jpeg"

    model_id = model or s.resolved_model("gemini")
    proxy = (s.llm_http_proxy or "").strip()
    env_extra: dict[str, str] = {}
    if s.llm_use_proxy and proxy:
        env_extra["HTTP_PROXY"] = proxy
        env_extra["HTTPS_PROXY"] = proxy

    contents = [
        genai_types.Part.from_bytes(data=raw, mime_type=mime),
        user_text,
    ]
    generate_kwargs: dict = {
        "model": model_id,
        "contents": contents,
        "config": genai_types.GenerateContentConfig(
            system_instruction=system,
            http_options=genai_types.HttpOptions(timeout=s.gemini_timeout_seconds * 1000),
        ),
    }

    max_attempts = 1 + max(0, s.gemini_max_retries)
    for attempt in range(max_attempts):
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
            return TranscribeResult(text, usage)
        except Exception as exc:
            try:
                from google.genai.errors import ClientError

                # 429 Resource Exhausted maps to ClientError with status 429
                if (
                    isinstance(exc, ClientError)
                    and getattr(exc, "status_code", None) == 429
                    and attempt + 1 < max_attempts
                ):
                    _sleep_backoff(attempt)
                    continue
            except ImportError:
                pass
            raise
    raise RuntimeError("Gemini: internal retry loop exited unexpectedly")
