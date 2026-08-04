"""Cerebras Cloud API (OpenAI-compatible) — extremely fast inference, free tier.

Free models (as of 2026):
  llama3.3-70b   (best quality, ~2000 tokens/s)
  llama3.1-8b    (fastest)

Text-only: Cerebras does not support vision in the free tier.
For transcription use llm_mode=correct (HTR draft as text input).

Get a free API key at https://cloud.cerebras.ai
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from transcriber_shell.config import Settings
from transcriber_shell.llm.transcribe import TranscribeResult

_CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
_RETRYABLE_STATUS = frozenset({429, 503})


def _sleep_backoff(attempt: int) -> None:
    base = min(32.0, 2.0**attempt)
    time.sleep(base + random.uniform(0.0, 1.0))


def transcribe_cerebras(
    *,
    image_path: Path | None,  # accepted but ignored — Cerebras is text-only
    system: str,
    user_text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> TranscribeResult:
    from openai import APIStatusError, OpenAI

    s = settings or Settings()
    if not s.cerebras_api_key:
        raise RuntimeError(
            "No Cerebras API key: set CEREBRAS_API_KEY in .env. "
            "Free key at https://cloud.cerebras.ai"
        )

    client = OpenAI(api_key=s.cerebras_api_key, base_url=_CEREBRAS_BASE_URL)
    model_id = model or s.resolved_model("cerebras")

    max_attempts = 1 + max(0, getattr(s, "cerebras_max_retries", 2))
    for attempt in range(max_attempts):
        try:
            r = client.chat.completions.create(
                model=model_id,
                max_tokens=8_000,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_text},
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
    raise RuntimeError("Cerebras: internal retry loop exited unexpectedly")
