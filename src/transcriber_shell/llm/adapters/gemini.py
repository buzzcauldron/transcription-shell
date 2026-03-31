"""Google Gemini — optional extra transcriber-shell[gemini]."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from transcriber_shell.config import Settings


def transcribe_gemini(
    *,
    image_path: Path,
    system: str,
    user_text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> str:
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
    with patch.dict(os.environ, env_extra, clear=False):
        r = gen_model.generate_content(
            [
                {"mime_type": mime, "data": raw},
                user_text,
            ]
        )
    return (r.text or "").strip()
