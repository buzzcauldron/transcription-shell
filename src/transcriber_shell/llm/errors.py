"""User-facing LLM failures (safe to show in GUI / logs; no raw secrets)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LLM_CAP_RE = re.compile(
    r"("
    r"\b429\b|"
    r"RESOURCE_EXHAUSTED|"
    r"RateLimitError|"
    r"rate limit \(429\)|"
    r"tokens? per day|"
    r"\bTPD\b|"
    r"token.?quota|"
    r"quota exceeded|"
    r"exceeded (?:your )?(?:current )?quota|"
    r"insufficient_quota|"
    r"free_tier|"
    r"all models in cycle exhausted|"
    r"Too Many Requests|"
    r"rate_limit_exceeded"
    r")",
    re.I,
)


_cap_tripped = False


def reset_llm_cap_trip() -> None:
    """Tests only."""
    global _cap_tripped
    _cap_tripped = False


def _stamp_job_llm_cap() -> None:
    """Persist ``status/llm.CAP`` so the next batch process (and the watcher) skip LLM."""
    raw = (
        os.environ.get("STREAM_JOB_DIR")
        or os.environ.get("TRANSCRIBER_SHELL_JOB_DIR")
        or ""
    ).strip()
    if not raw:
        return
    marker = Path(raw) / "status" / "llm.CAP"
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        if not marker.is_file():
            marker.write_text(
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z") + "\n",
                encoding="utf-8",
            )
    except OSError:
        pass


def trip_llm_cap() -> None:
    """After a quota/429 wall, remaining pages skip autocorrect (HTR is kept)."""
    global _cap_tripped
    _cap_tripped = True
    _stamp_job_llm_cap()


def llm_cap_tripped() -> bool:
    if _cap_tripped:
        return True
    env = (
        os.environ.get("TRANSCRIBER_SHELL_LLM_SKIP_ON_CAP")
        or os.environ.get("STREAM_LLM_SKIP_ON_CAP")
        or ""
    ).strip().lower()
    return env in ("1", "true", "yes", "on")


class LLMProviderError(Exception):
    """Raised when an LLM adapter has a clear, user-facing explanation."""


def is_llm_cap_error(exc_or_text: Any) -> bool:
    """True for quota / daily-token / 429 walls (not generic LLM failures)."""
    return bool(_LLM_CAP_RE.search(str(exc_or_text or "")))


def skip_retries_on_llm_cap(settings: Any, exc: BaseException) -> bool:
    """Autocorrect (``llm_mode=correct``) must not wait out a cap — keep HTR."""
    mode = str(getattr(settings, "llm_mode", None) or "full").strip().lower()
    if mode != "correct":
        return False
    code = getattr(exc, "status_code", None)
    try:
        if int(code) == 429:
            return True
    except (TypeError, ValueError):
        pass
    return is_llm_cap_error(exc)
