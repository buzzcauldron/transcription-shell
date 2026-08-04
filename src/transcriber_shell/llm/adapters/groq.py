"""Groq Cloud API (OpenAI-compatible) — free tier includes vision and 70B text models.

Free models (as of 2026):
  Vision:  llama-3.2-11b-vision-preview  (transcription, multimodal)
  Text:    llama-3.3-70b-versatile, llama-3.1-8b-instant  (correction, translation)

Get a free API key at https://console.groq.com
"""

from __future__ import annotations

import base64
import random
import time
from pathlib import Path

from transcriber_shell.config import Settings
from transcriber_shell.llm.transcribe import TranscribeResult

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_RETRYABLE_STATUS = frozenset({429, 503})


def _sleep_backoff(attempt: int) -> None:
    base = min(32.0, 2.0**attempt)
    time.sleep(base + random.uniform(0.0, 1.0))


def transcribe_groq(
    *,
    image_path: Path | None,
    system: str,
    user_text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> TranscribeResult:
    from openai import APIStatusError, OpenAI

    s = settings or Settings()
    if not s.groq_api_key:
        raise RuntimeError(
            "No Groq API key: set GROQ_API_KEY in .env. "
            "Free key at https://console.groq.com"
        )

    client = OpenAI(api_key=s.groq_api_key, base_url=_GROQ_BASE_URL)
    model_id = model or s.resolved_model("groq")

    if image_path is not None:
        from transcriber_shell.llm.image_prep import prepare_image
        raw, media = prepare_image(image_path)
        b64 = base64.standard_b64encode(raw).decode("ascii")
        user_content = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": f"data:{media};base64,{b64}"}},
        ]
    else:
        user_content = user_text

    max_attempts = 1 + max(0, getattr(s, "groq_max_retries", 2))
    for attempt in range(max_attempts):
        try:
            r = client.chat.completions.create(
                model=model_id,
                max_tokens=8_000,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            text = r.choices[0].message.content or ""
            usage = None
            ru = getattr(r, "usage", None)
            if ru is not None:
                pt = getattr(ru, "prompt_tokens", None)
                ct = getattr(ru, "completion_tokens", None)
                if pt is not None or ct is not None:
                    usage = {}
                    if pt is not None:
                        usage["input_tokens"] = int(pt)
                    if ct is not None:
                        usage["output_tokens"] = int(ct)
                    if pt is not None and ct is not None:
                        usage["total_tokens"] = int(pt) + int(ct)
            return TranscribeResult(text, usage)
        except APIStatusError as e:
            if e.status_code in _RETRYABLE_STATUS and attempt + 1 < max_attempts:
                _sleep_backoff(attempt)
                continue
            raise
    raise RuntimeError("Groq: internal retry loop exited unexpectedly")
