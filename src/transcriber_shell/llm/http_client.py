"""Optional httpx client for cloud LLM adapters (HTTP proxy)."""

from __future__ import annotations

import httpx

from transcriber_shell.config import Settings


def llm_httpx_client(
    settings: Settings,
    *,
    timeout_seconds: float,
) -> httpx.Client | None:
    """Return a configured client when proxy is enabled and URL is set; else None."""
    if not settings.llm_use_proxy:
        return None
    proxy = (settings.llm_http_proxy or "").strip()
    if not proxy:
        return None
    connect = min(60.0, max(5.0, timeout_seconds / 10))
    timeout = httpx.Timeout(timeout_seconds, connect=connect)
    return httpx.Client(proxy=proxy, timeout=timeout)
