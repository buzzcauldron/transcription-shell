"""OpenAI chat completions with vision."""

from __future__ import annotations

import base64
import random
import time
from pathlib import Path

from transcriber_shell.config import Settings
from transcriber_shell.llm.http_client import llm_httpx_client
from transcriber_shell.llm.transcribe import TranscribeResult

_RETRYABLE_STATUS = frozenset({429, 503})


def _mime_for_path(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suf == ".png":
        return "image/png"
    if suf == ".webp":
        return "image/webp"
    return "image/jpeg"


def _sleep_backoff(attempt: int) -> None:
    base = min(32.0, 2.0**attempt)
    time.sleep(base + random.uniform(0.0, 1.0))


def transcribe_openai(
    *,
    image_path: Path,
    system: str,
    user_text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> TranscribeResult:
    from openai import APIStatusError, OpenAI

    s = settings or Settings()
    if not s.openai_api_key:
        raise RuntimeError(
            "No OpenAI API key: set OPENAI_API_KEY or TRANSCRIBER_SHELL_OPENAI_API_KEY "
            "in .env or paste under Provider keys in the GUI."
        )
    http_client = llm_httpx_client(s, timeout_seconds=s.openai_timeout_seconds)
    client_kw: dict = {"api_key": s.openai_api_key}
    if http_client is not None:
        client_kw["http_client"] = http_client
    client = OpenAI(**client_kw)
    raw = image_path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    media = _mime_for_path(image_path)
    url = f"data:{media};base64,{b64}"

    model_id = model or s.resolved_model("openai")
    max_attempts = 1 + max(0, s.openai_max_retries)

    for attempt in range(max_attempts):
        try:
            r = client.chat.completions.create(
                model=model_id,
                max_tokens=32_000,
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {"type": "image_url", "image_url": {"url": url}},
                        ],
                    },
                ],
            )
            choice = r.choices[0].message.content
            text = choice or ""
            usage: dict[str, int] | None = None
            ru = getattr(r, "usage", None)
            if ru is not None:
                pt = getattr(ru, "prompt_tokens", None)
                ct = getattr(ru, "completion_tokens", None)
                tt = getattr(ru, "total_tokens", None)
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
        except APIStatusError as e:
            if e.status_code in _RETRYABLE_STATUS and attempt + 1 < max_attempts:
                _sleep_backoff(attempt)
                continue
            raise
    raise RuntimeError("OpenAI: internal retry loop exited unexpectedly")
