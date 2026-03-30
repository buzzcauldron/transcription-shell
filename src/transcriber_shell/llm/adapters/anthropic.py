"""Anthropic Messages API — image + system + user text."""

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
    if suf == ".gif":
        return "image/gif"
    return "application/octet-stream"


def transcribe_anthropic(
    *,
    image_path: Path,
    system: str,
    user_text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> str:
    import anthropic

    s = settings or Settings()
    if not s.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY / TRANSCRIBER_SHELL_ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=s.anthropic_api_key)
    raw = image_path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    media = _mime_for_path(image_path)

    model_id = model or s.resolved_model("anthropic")
    msg = client.messages.create(
        model=model_id,
        max_tokens=32_000,
        system=system,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    )
    parts: list[str] = []
    for block in msg.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts)
