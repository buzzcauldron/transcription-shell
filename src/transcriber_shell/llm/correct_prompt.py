"""Short HTR-correct prompts (Phase 3) — draft-primary, not full protocol re-transcription."""

from __future__ import annotations

CORRECT_SYSTEM_DIPLOMATIC = """\
You correct an HTR machine draft of a manuscript page into Academic Transcription Protocol YAML.

Rules:
- The HTR draft in the user message is the PRIMARY and only source — correct its errors, do not rewrite it.
- Fix obvious misreads (wrong letters, broken words, digit confusion) while preserving the draft structure.
- Do NOT re-transcribe the page from scratch.
- Output ONLY valid YAML matching the protocol shape below (no markdown fences, no commentary).
- DIPLOMATIC MODE: preserve abbreviation marks, suspensions, and ink forms as written.
  Do NOT expand ẽt→et, p̃benda→prebenda, Tironian notes, etc. Keep diacritics that mark abbreviation.
- Keep Roman numerals as Roman numerals; do not convert to Arabic.
- Segment count / lineRange should follow the HTR line breaks when possible.

Minimal YAML shape:
```
transcriptionOutput:
  metadata:
    language: <BCP-47 or script tag from context>
    normalizationMode: diplomatic
  segments:
    - lineRange: [1, 1]
      text: "<diplomatic text for line 1>"
    - lineRange: [2, 2]
      text: "<...>"
```
"""

CORRECT_SYSTEM_NORMALIZED = """\
You correct an HTR machine draft of a manuscript page into Academic Transcription Protocol YAML.

Rules:
- The HTR draft in the user message is the PRIMARY and only source — correct its errors, do not rewrite it.
- Fix obvious misreads (wrong letters, broken words, digit confusion) while preserving the draft structure.
- Do NOT re-transcribe the page from scratch.
- Output ONLY valid YAML matching the protocol shape below (no markdown fences, no commentary).
- NORMALIZED MODE: expand common abbreviation marks in segment `text`
  (ẽt→et, p̃benda→prebenda, q̃d→quod, Tironian et→et, etc.) and drop abbreviation diacritics
  once expanded. Keep Roman numerals as Roman numerals.
- Segment count / lineRange should follow the HTR line breaks when possible.

Minimal YAML shape:
```
transcriptionOutput:
  metadata:
    language: <BCP-47 or script tag from context>
    normalizationMode: normalized
  segments:
    - lineRange: [1, 1]
      text: "<normalized text for line 1>"
    - lineRange: [2, 2]
      text: "<...>"
```
"""


def build_correct_prompts(
    *,
    line_hint: str,
    normalization_mode: str,
    language_hint: str | None = None,
) -> tuple[str, str]:
    """Return (system, user_text) for llm_mode=correct with HTR drafts present."""
    norm = (normalization_mode or "diplomatic").strip().lower()
    diplomatic = norm not in ("normalized", "normalised")
    system = CORRECT_SYSTEM_DIPLOMATIC if diplomatic else CORRECT_SYSTEM_NORMALIZED
    lang = (language_hint or "").strip()
    lang_line = f"Language/script context: {lang}\n" if lang else ""
    user = (
        f"{lang_line}"
        "Correct the following HTR draft(s) into protocol YAML.\n\n"
        f"{line_hint.strip()}\n"
    )
    return system, user


def should_use_short_correct(llm_mode: str, line_hint: str | None) -> bool:
    return (
        (llm_mode or "full").strip().lower() == "correct"
        and bool(line_hint)
        and "HTR machine-readable drafts" in line_hint
    )
