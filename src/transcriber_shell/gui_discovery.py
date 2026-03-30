"""Probe local AI runtimes and CLI tools (no extra dependencies)."""

from __future__ import annotations

import json
import shutil
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _http_json(url: str, *, method: str = "GET", data: bytes | None = None, timeout: float = 2.5) -> Any:
    req = Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def probe_ollama_model_names(base_url: str) -> list[str]:
    """Return model names from Ollama ``/api/tags``, or empty list."""
    base = base_url.rstrip("/")
    try:
        data = _http_json(f"{base}/api/tags", timeout=2.5)
    except (HTTPError, URLError, OSError, json.JSONDecodeError, ValueError):
        return []
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []
    out: list[str] = []
    for m in models:
        if isinstance(m, dict):
            name = m.get("name")
            if isinstance(name, str) and name.strip():
                out.append(name.strip())
    return sorted(set(out))


def probe_openai_compatible_models(base_url: str) -> list[str]:
    """LM Studio, vLLM, etc.: ``GET /v1/models``."""
    base = base_url.rstrip("/")
    try:
        data = _http_json(f"{base}/v1/models", timeout=2.5)
    except (HTTPError, URLError, OSError, json.JSONDecodeError, ValueError):
        return []
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            mid = row.get("id")
            if isinstance(mid, str) and mid.strip():
                out.append(mid.strip())
    return sorted(set(out))


def find_cli_tools() -> dict[str, str]:
    """Resolve common GUI/CLI names on PATH."""
    names = (
        "ollama",
        "transcriber-shell",
        "python3",
        "python",
        "uvicorn",
        "code",
        "cursor",
    )
    found: dict[str, str] = {}
    for n in names:
        p = shutil.which(n)
        if p:
            found[n] = p
    return found


def format_discovery_report(
    *,
    ollama_base: str,
    lm_studio_base: str = "http://127.0.0.1:1234",
) -> tuple[list[str], list[str]]:
    """Return (log_lines, ollama_model_names)."""
    lines: list[str] = []
    lines.append("— Discovery —")

    ollama_models = probe_ollama_model_names(ollama_base)
    if ollama_models:
        lines.append(f"Ollama at {ollama_base}: {len(ollama_models)} model(s) — e.g. {', '.join(ollama_models[:8])}")
        if len(ollama_models) > 8:
            lines.append(f"  … +{len(ollama_models) - 8} more (use Custom model id or pick provider «ollama»)")
    else:
        lines.append(f"No Ollama response at {ollama_base} (start with: ollama serve)")

    lm_models = probe_openai_compatible_models(lm_studio_base)
    if lm_models:
        lines.append(
            f"OpenAI-compatible at {lm_studio_base}: {len(lm_models)} model id(s) listed — copy an id into Custom model if you use a compatible HTTP API elsewhere."
        )
    else:
        lines.append(f"No /v1/models at {lm_studio_base} (try LM Studio local server when running).")

    cli = find_cli_tools()
    if cli:
        lines.append("PATH tools:")
        for k, v in sorted(cli.items()):
            lines.append(f"  {k}: {v}")
    else:
        lines.append("No matching CLI tools on PATH.")

    lines.append(f"Python: {sys.executable}")
    return lines, ollama_models
