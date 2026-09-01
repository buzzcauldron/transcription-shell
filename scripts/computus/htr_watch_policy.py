"""Harvest HTR completion rules.

False ``pipeline.DONE`` stamps were the main harvest stall: watchers marked every
``.failed`` page as finished, then wrote DONE with zero YAML. Keep completion
tied to YAML (+ skip) coverage, and keep print-dump acquires out of the HTR queue.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

DONEISH_RATIO = 0.9
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2", ".webp"}

_RETRYABLE_ERROR_RE = re.compile(
    r"(Kraken model not found|Cannot reach Ollama|"
    r"/Users/[^ \n]+latin_documents|"
    r"Is `ollama serve` running)",
    re.I,
)
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
_PRINT_DUMP_RE = re.compile(
    r"(noticesetextrai|[a-z0-9]{3,}goog(?:[_.]|$)|bub_gb_)",
    re.I,
)


def coverage_ok(
    n_yaml: int,
    n_skipped: int,
    n_pages: int,
    *,
    ratio: float = DONEISH_RATIO,
) -> bool:
    """True when YAML plus skipped pages cover ``ratio`` of staged pages."""
    if n_pages <= 0:
        return False
    return (n_yaml + n_skipped) >= math.ceil(n_pages * ratio)


def is_retryable_htr_error(log_text: str) -> bool:
    """Infra to retry (missing Kraken / Ollama). LLM caps are not retryable."""
    text = log_text or ""
    if is_llm_cap_error(text):
        return False
    return bool(_RETRYABLE_ERROR_RE.search(text))


def is_llm_cap_error(log_text: str) -> bool:
    """Quota / 429 / tokens-per-day — keep HTR and move on."""
    return bool(_LLM_CAP_RE.search(log_text or ""))


def is_foreign_os_model_path(path: str | Path | None, *, platform: str) -> bool:
    """Mac ``/Users/`` checkpoints must not be used on Linux lab hosts."""
    if path is None:
        return False
    text = str(path).replace("\\", "/")
    if not text:
        return False
    plat = (platform or "").lower()
    if plat != "darwin" and "/Users/" in text:
        return True
    return False


def looks_like_print_dump(job_id: str, image_names: list[str] | None = None) -> bool:
    """Google Books / *Notices et extraits* IA dumps, not manuscript page sets."""
    blob = f"{job_id} {' '.join(image_names or [])}"
    if _PRINT_DUMP_RE.search(blob):
        return True
    names = image_names or []
    if not names:
        return False
    sample = names[:30]
    hits = sum(1 for n in sample if re.search(r"[a-z0-9]{3,}goog", n, re.I))
    return hits >= max(3, len(sample) // 2)


def sample_image_names(job: Path, limit: int = 30) -> list[str]:
    src = job / "00_sources_chunks"
    if not src.is_dir():
        return []
    names: list[str] = []
    for p in src.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            names.append(p.name)
            if len(names) >= limit:
                break
    return names


def count_yaml_pages(job: Path) -> int:
    art = job / "03_artifacts_2500"
    if not art.is_dir():
        return 0
    n = 0
    for p in art.rglob("*_transcription.yaml"):
        if p.is_file():
            n += 1
    return n


def count_skipped_pages(job: Path) -> int:
    art = job / "03_artifacts_2500"
    if not art.is_dir():
        return 0
    return sum(1 for _ in art.rglob(".skipped"))


def count_staged_pages(job: Path) -> int:
    pages = job / "01_pages_2500"
    if pages.is_dir():
        n = sum(1 for p in pages.glob("*.jpg") if p.is_file())
        if n:
            return n
    src = job / "00_sources_chunks"
    if not src.is_dir():
        return 0
    return sum(1 for p in src.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def job_is_doneish(job: Path, *, ratio: float = DONEISH_RATIO) -> bool:
    return coverage_ok(
        count_yaml_pages(job),
        count_skipped_pages(job),
        count_staged_pages(job),
        ratio=ratio,
    )


def yaml_is_htr_only(path: Path) -> bool:
    """True when YAML notes say on-machine HTR with no LLM autocorrect."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2500]
    except OSError:
        return False
    return "htr_only" in head


def job_has_llm_cap(job: Path) -> bool:
    return (job / "status" / "llm.CAP").is_file()


def count_corrected_yaml_pages(job: Path) -> int:
    """YAML pages that already have LLM autocorrect (not ``htr_only`` / ``.needs_llm``)."""
    art = job / "03_artifacts_2500"
    if not art.is_dir():
        return 0
    n = 0
    for p in art.rglob("*_transcription.yaml"):
        if not p.is_file():
            continue
        if (p.parent / ".needs_llm").is_file():
            continue
        if yaml_is_htr_only(p):
            continue
        n += 1
    return n


def job_is_htr_queue_doneish(
    job: Path,
    *,
    llm_mode: str | None = None,
    ratio: float = DONEISH_RATIO,
) -> bool:
    """Queue completion: HTR coverage, plus LLM autocorrect unless capped or mode=off."""
    n_pages = count_staged_pages(job)
    n_skip = count_skipped_pages(job)
    mode = coerce_llm_mode(llm_mode)
    if mode == "off" or job_has_llm_cap(job):
        return coverage_ok(count_yaml_pages(job), n_skip, n_pages, ratio=ratio)
    return coverage_ok(count_corrected_yaml_pages(job), n_skip, n_pages, ratio=ratio)


# Harvest pipeline: LLM is HTR autocorrect only. Expand is expand-diplomatic rules.
ALLOWED_LLM_MODES = frozenset({"off", "correct"})
LLM_EXPAND_BACKENDS = frozenset({"groq", "local", "gemini", "anthropic"})


def coerce_llm_mode(mode: str | None) -> str:
    """Default ``correct``. ``off`` stays off. ``full`` and other values become ``correct``."""
    s = (mode or "correct").strip().lower() or "correct"
    if s in ALLOWED_LLM_MODES:
        return s
    return "correct"


def coerce_expand_backend(backend: str | None) -> str:
    """Always ``rules`` in this pipeline (no LLM expand)."""
    del backend
    return "rules"
