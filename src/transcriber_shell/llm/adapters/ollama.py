"""Local Ollama /api/chat with vision (no cloud API key)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from transcriber_shell.config import Settings


def transcribe_ollama(
    *,
    image_path: Path,
    system: str,
    user_text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> str:
    s = settings or Settings()
    base = str(s.ollama_base_url).rstrip("/")
    model_id = model or s.resolved_model("ollama")

    raw = image_path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user_text,
                "images": [b64],
            },
        ],
        "stream": False,
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{base}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(
            f"Ollama HTTP {e.code} at {base}/api/chat: {err_body or e.reason}. "
            "Check `ollama list` for the model id and pull it if missing."
        ) from e
    except URLError as e:
        raise RuntimeError(
            f"Cannot reach Ollama at {base}. Is `ollama serve` running? ({e.reason})"
        ) from e

    msg = data.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    raise RuntimeError(
        f"Ollama returned no assistant text (model={model_id!r}). "
        f"Response was: {data!r}. Try a vision-capable model (e.g. llava)."
    )
