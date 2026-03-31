"""OpenAI chat completions with vision."""

from __future__ import annotations

import base64
from pathlib import Path

from transcriber_shell.config import Settings
from transcriber_shell.llm.http_client import llm_httpx_client


def _mime_for_path(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suf == ".png":
        return "image/png"
    if suf == ".webp":
        return "image/webp"
    return "image/jpeg"


def transcribe_openai(
    *,
    image_path: Path,
    system: str,
    user_text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> str:
    from openai import OpenAI

    s = settings or Settings()
    if not s.openai_api_key:
        raise RuntimeError(
            "No OpenAI API key: set OPENAI_API_KEY or TRANSCRIBER_SHELL_OPENAI_API_KEY "
            "in .env or paste under Provider keys in the GUI."
        )
    http_client = llm_httpx_client(s, timeout_seconds=600.0)
    client_kw = {"api_key": s.openai_api_key}
    if http_client is not None:
        client_kw["http_client"] = http_client
    client = OpenAI(**client_kw)
    raw = image_path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    media = _mime_for_path(image_path)
    url = f"data:{media};base64,{b64}"

    model_id = model or s.resolved_model("openai")
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
    return choice or ""
