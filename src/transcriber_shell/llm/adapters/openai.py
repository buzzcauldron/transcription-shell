"""OpenAI chat completions with vision."""

from __future__ import annotations

import base64
from pathlib import Path

from transcriber_shell.config import Settings


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
        raise RuntimeError("OPENAI_API_KEY / TRANSCRIBER_SHELL_OPENAI_API_KEY not set")
    client = OpenAI(api_key=s.openai_api_key)
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
