"""Optional second-pass translation of a finished diplomatic transcript.

Reuses the same provider adapters that ran the transcription. The image is
re-supplied so the LLM has visual context alongside the diplomatic text,
which materially improves translation quality on damaged or ambiguous lines.

Output is plain UTF-8 text saved next to the transcription YAML as
``<image_stem>_translation.txt`` — outside the protocol's diplomatic
boundary (see vendor/transcription-protocol normalization add-on §1.1:
translation is not part of normalization either).
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from transcriber_shell.config import Settings
from transcriber_shell.llm.transcribe import strip_yaml_fence


class TranslateResult(NamedTuple):
    text: str
    usage: dict[str, int] | None


_TRANSLATE_SYSTEM = (
    "You are translating a diplomatically transcribed historical manuscript or "
    "early modern printed page into clear, modern {target_language}. "
    "Treat the diplomatic text as authoritative for what is on the page, but use "
    "the supplied page image only to disambiguate uncertain tokens "
    "(e.g. [unc:abc?], [exp:...]). "
    "Do not invent missing material — if something is illegible in both the "
    "image and the diplomatic text, mark it with [illegible]. "
    "Preserve paragraph structure and line breaks where possible. "
    "Output the translation only — no commentary, no headers, no Markdown."
)


def run_translate(
    *,
    image_path: Path,
    diplomatic_text: str,
    provider: str,
    model: str | None,
    settings: Settings | None = None,
    target_language: str = "English",
) -> TranslateResult:
    """Run a translation pass via the configured provider.

    Returns the translated text (YAML/markdown fences stripped) and provider usage.
    """
    s = settings or Settings()
    system = _TRANSLATE_SYSTEM.format(target_language=target_language)
    user_text = (
        f"Translate the following diplomatic transcript into {target_language}. "
        "The page image accompanies it for visual reference.\n\n"
        "=== DIPLOMATIC TRANSCRIPT ===\n"
        f"{diplomatic_text}\n"
        "=== END DIPLOMATIC TRANSCRIPT ==="
    )

    p = provider.lower()
    if p == "anthropic":
        from transcriber_shell.llm.adapters.anthropic import transcribe_anthropic as fn
    elif p == "openai":
        from transcriber_shell.llm.adapters.openai import transcribe_openai as fn
    elif p == "gemini":
        from transcriber_shell.llm.adapters.gemini import transcribe_gemini as fn
    elif p == "ollama":
        from transcriber_shell.llm.adapters.ollama import transcribe_ollama as fn
    else:
        raise ValueError(
            f"Unknown provider {provider!r}. Use anthropic, openai, gemini, or ollama."
        )

    r = fn(
        image_path=image_path,
        system=system,
        user_text=user_text,
        model=model,
        settings=s,
    )
    return TranslateResult(text=strip_yaml_fence(r.text).strip(), usage=r.usage)


def translation_output_path(transcription_yaml: Path) -> Path:
    """Sibling path: <stem>_transcription.yaml → <stem>_translation.txt."""
    yaml_path = Path(transcription_yaml)
    name = yaml_path.name
    if name.endswith("_transcription.yaml"):
        return yaml_path.with_name(name[: -len("_transcription.yaml")] + "_translation.txt")
    return yaml_path.with_suffix(".translation.txt")
