"""Format HTR drafts and per-stage timings for logs / GUI panes."""

from __future__ import annotations

from typing import Any


def format_timings(timings: list[tuple[str, float]] | None) -> str | None:
    """ASCII bar chart of per-stage timings, or None if empty."""
    if not timings:
        return None
    total = sum(s for _, s in timings)
    max_s = max(s for _, s in timings) or 1.0
    parts = []
    for label, s in timings:
        bar = "█" * max(1, int(s / max_s * 20))
        parts.append(f"  {label:<12} {s:>5.1f}s  {bar}")
    return f"timings (total {total:.1f}s):\n" + "\n".join(parts)


def format_htr_drafts(
    htr_results: dict[str, Any] | None,
    *,
    max_chars_per_backend: int = 4000,
    preview_only: bool = False,
) -> str | None:
    """Human-readable HTR draft text for GUI / logs.

    Accepts live ``HtrResult`` objects or batch-report dicts
    (``{backend, line_count, text_preview, error}``).
    """
    if not htr_results:
        return None
    from transcriber_shell.htr.base import HtrResult

    blocks: list[str] = []
    for name, v in htr_results.items():
        if isinstance(v, Exception):
            blocks.append(f"=== {name} ===\nERROR: {v}")
            continue
        if isinstance(v, HtrResult):
            body = (v.text or "").strip()
            if max_chars_per_backend and len(body) > max_chars_per_backend:
                body = body[:max_chars_per_backend] + "\n[… truncated …]"
            conf = v.confidence or "n/a"
            blocks.append(
                f"=== {name} ({v.line_count} lines, confidence={conf}) ===\n{body or '(empty)'}"
            )
            continue
        if isinstance(v, dict):
            if v.get("error"):
                blocks.append(f"=== {name} ===\nERROR: {v['error']}")
                continue
            preview = (v.get("text_preview") or v.get("text") or "").strip()
            if preview_only and not preview:
                continue
            lc = v.get("line_count", "?")
            conf = v.get("confidence", "n/a")
            blocks.append(f"=== {name} ({lc} lines, confidence={conf}) ===\n{preview or '(empty)'}")
            continue
        blocks.append(f"=== {name} ===\n{v!r}")
    if not blocks:
        return None
    return "\n\n".join(blocks)
