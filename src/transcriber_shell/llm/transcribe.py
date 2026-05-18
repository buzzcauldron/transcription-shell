"""Build protocol prompts (via vendored prompt_builder) and call a provider."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from transcriber_shell.config import Settings
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.protocol_paths import ensure_prompt_builder_on_path


class TranscribeResult(NamedTuple):
    """LLM response text and optional token usage (provider-dependent)."""

    text: str
    usage: dict[str, int] | None


_EXPANSION_GUIDE_PATH = (
    Path(__file__).resolve().parents[2].parent / "docs" / "abbreviation-expansion.md"
)
_expansion_guide_cache: str | None = None


def _load_expansion_guide() -> str:
    """Read the bundled normalized-mode abbreviation expansion guide (cached)."""
    global _expansion_guide_cache
    if _expansion_guide_cache is not None:
        return _expansion_guide_cache
    try:
        _expansion_guide_cache = _EXPANSION_GUIDE_PATH.read_text(encoding="utf-8")
    except OSError:
        _expansion_guide_cache = ""
    return _expansion_guide_cache


def run_transcribe(job: TranscribeJob, settings: Settings | None = None) -> TranscribeResult:
    ensure_prompt_builder_on_path(settings)
    from prompt_builder import build_zones

    s = settings or Settings()
    cfg = dict(job.prompt_cfg)
    extra = ""
    if job.line_hint:
        extra = f"\nLINEATION NOTE (for segment lineRange consistency): {job.line_hint}\n"
    system, user_text = build_zones(cfg)
    user_text = user_text + extra
    # normalizationMode=normalized: inject the expansion reference so the LLM expands
    # ẽt→et, p̃benda→prebenda, drops abbreviation diacritics, etc.
    if str(cfg.get("normalizationMode") or "").strip().lower() == "normalized":
        guide = _load_expansion_guide()
        if guide:
            system = (
                system
                + "\n\nNORMALIZED MODE — abbreviation expansion is REQUIRED. Every "
                "abbreviation glyph (tilde over vowel, macron, suspension stroke, "
                "p/q ligatures, Tironian et, long-s, round-r, etc.) must be expanded "
                "to its full Latin word in the segment `text`. The reader must not see "
                "ẽt, p̃benda, q̃d, m̃ — they must see et, prebenda, quod, mm/mn. "
                "Drop diacritics that mark abbreviation once the expansion is supplied. "
                "Follow the rules in the reference below.\n\n"
                + guide
            )
    # llm_mode=correct: treat HTR drafts in the user message as the primary content;
    # do not re-transcribe from scratch. The full protocol output is still required.
    if (s.llm_mode or "full").lower() == "correct" and job.line_hint and "HTR machine-readable drafts" in job.line_hint:
        system = (
            system
            + "\n\nCORRECT MODE: An HTR machine draft is provided in the user message. "
            "Treat it as the primary source of character recognition; your job is to fix "
            "obvious recognition errors (e.g. expand abbreviation marks like ẽt→et, "
            "p̃benda→prebenda) and arbitrate where multiple drafts disagree. Do NOT re-read "
            "the image from scratch; use it only to resolve ambiguous spots in the draft. "
            "Preserve the protocol YAML output format."
        )

    provider = job.provider.lower()
    mo = job.model_override
    if provider == "anthropic":
        from transcriber_shell.llm.adapters.anthropic import transcribe_anthropic

        return transcribe_anthropic(
            image_path=job.image_path,
            system=system,
            user_text=user_text,
            model=mo,
            settings=s,
        )
    if provider == "openai":
        from transcriber_shell.llm.adapters.openai import transcribe_openai

        return transcribe_openai(
            image_path=job.image_path,
            system=system,
            user_text=user_text,
            model=mo,
            settings=s,
        )
    if provider == "gemini":
        from transcriber_shell.llm.adapters.gemini import transcribe_gemini

        return transcribe_gemini(
            image_path=job.image_path,
            system=system,
            user_text=user_text,
            model=mo,
            settings=s,
        )
    if provider == "ollama":
        from transcriber_shell.llm.adapters.ollama import transcribe_ollama

        return transcribe_ollama(
            image_path=job.image_path,
            system=system,
            user_text=user_text,
            model=mo,
            settings=s,
        )
    raise ValueError(
        f"Unknown provider {job.provider!r}. Use anthropic, openai, gemini, or ollama "
        "(see Provider in the GUI or --provider on the CLI)."
    )


def strip_yaml_fence(text: str) -> str:
    """Remove optional ```yaml ... ``` wrapper from model output."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    return t
