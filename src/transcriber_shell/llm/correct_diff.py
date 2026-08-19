"""Diff-based HTR correction: ask for changed lines only, merge locally.

WHY
---
Correct mode is supposed to fix recognition errors in an HTR draft, but the
output contract made the model re-emit the whole page as protocol YAML. Measured
on the workspace: median corrected YAML is 9,182 bytes (~2,295 output tokens)
against a raw draft of 3,059 bytes -- roughly 3x the input, and output bills at
~5x input, so the rewrite dominates the bill. At sonnet-class rates that is about
$0.04-0.05/page, i.e. $800-1,000 for one pass over the 20,727-page workspace.

It also explains a quality problem seen earlier: corrected pages diverged from
the HTR by 0.93-0.99 of characters -- a full rewrite, not a correction. A prompt
asking for restraint did not prevent that because the output format *required*
re-emitting everything.

So change the contract. The draft is sent as numbered lines and the model returns
only the lines it would change:

    corrections:
      - line: 12
        text: "corrected reading"

Every unlisted line is kept verbatim from the draft. A page needing five fixes
emits five short entries instead of eighty segments, and wholesale regeneration
becomes structurally impossible rather than merely discouraged.

Parsing is deliberately tolerant: a model that ignores the instruction and
returns full protocol YAML is still handled, so enabling this cannot silently
produce empty transcriptions.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

DIFF_SYSTEM = """\
You correct an HTR machine draft of a manuscript page. The draft is given as
numbered lines.

Return ONLY the lines you would change, as YAML:

corrections:
  - line: <line number>
    text: "<corrected reading for that line>"

Rules:
- Output ONLY this YAML. No markdown fences, no commentary, no other keys.
- Include a line ONLY if you are changing it. Every line you omit is kept exactly
  as the draft has it.
- Fix clear recognition errors: wrong letters, broken or run-together words,
  digit/letter confusion, mis-split lines.
- Do NOT retranscribe, restyle, translate, reorder, merge or split lines, or
  "improve" wording that is already defensible.
- If the draft line is already acceptable, leave it out.
- If nothing needs changing, return exactly:  corrections: []
%(mode)s"""

_DIPLOMATIC = """\
- DIPLOMATIC MODE: keep abbreviation marks, suspensions and ink forms as written.
  Do not expand them. Keep Roman numerals as Roman numerals."""

_NORMALIZED = """\
- NORMALIZED MODE: expand abbreviation marks in the text you return, and drop the
  abbreviation diacritics once expanded. Keep Roman numerals as Roman numerals."""


def number_draft(text: str) -> tuple[str, list[str]]:
    """Return (numbered block, original lines). Lines are 1-indexed in the block."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    numbered = "\n".join(f"{i}| {ln}" for i, ln in enumerate(lines, 1))
    return numbered, lines


def build_diff_prompts(
    *, draft: str, normalization_mode: str, language_hint: str | None = None
) -> tuple[str, str, list[str]]:
    """Return (system, user, draft_lines) for a diff-based correction call."""
    norm = (normalization_mode or "diplomatic").strip().lower()
    mode = _NORMALIZED if norm in ("normalized", "normalised") else _DIPLOMATIC
    system = DIFF_SYSTEM % {"mode": mode}
    numbered, lines = number_draft(draft)
    lang = (language_hint or "").strip()
    user = (
        (f"Language/script context: {lang}\n" if lang else "")
        + f"HTR draft ({len(lines)} lines):\n\n{numbered}\n"
    )
    return system, user, lines


_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


def parse_corrections(raw: str) -> dict[int, str] | None:
    """Parse a corrections response into {line_number: corrected_text}.

    Returns None when the response is not a corrections document -- for example a
    model that ignored the format and returned full protocol YAML. The caller then
    falls back to treating the response as a normal transcript, so switching this
    on cannot silently blank a page.
    """
    if not raw or not raw.strip():
        return None
    text = _FENCE_RE.sub("", raw.strip())
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    if "transcriptionOutput" in data:
        return None          # full protocol YAML -- not a diff
    if "corrections" not in data:
        return None
    items = data.get("corrections")
    if items is None:
        return {}
    if not isinstance(items, list):
        return None
    out: dict[int, str] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        ln = it.get("line")
        tx = it.get("text")
        if isinstance(ln, bool) or not isinstance(ln, int):
            continue
        if not isinstance(tx, str):
            continue
        out[ln] = tx
    return out


def apply_corrections(lines: list[str], corrections: dict[int, str]) -> tuple[list[str], list[int]]:
    """Apply 1-indexed corrections to draft lines. Returns (merged, ignored_line_numbers).

    Out-of-range line numbers are reported rather than applied or silently
    dropped: a hallucinated line number means the model lost track of the draft,
    which the caller should be able to see.
    """
    merged = list(lines)
    ignored: list[int] = []
    for ln, tx in sorted(corrections.items()):
        if 1 <= ln <= len(merged):
            merged[ln - 1] = tx
        else:
            ignored.append(ln)
    return merged, ignored


def corrections_to_transcript(
    merged: list[str], *, normalization_mode: str, model_id: str
) -> dict[str, Any]:
    """Build a minimal protocol-shaped transcript from merged draft lines."""
    norm = (normalization_mode or "diplomatic").strip().lower()
    return {
        "transcriptionOutput": {
            "metadata": {
                "normalizationMode": "normalized" if norm in ("normalized", "normalised")
                                     else "diplomatic",
                "modelId": model_id,
            },
            "segments": [
                {"lineRange": [i, i], "text": ln}
                for i, ln in enumerate(merged, 1)
                if ln.strip()
            ],
        }
    }
