"""Build protocol prompts (via vendored prompt_builder) and call a provider."""

from __future__ import annotations

from pathlib import Path

from transcriber_shell.config import Settings
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.protocol_paths import ensure_prompt_builder_on_path


def run_transcribe(job: TranscribeJob, settings: Settings | None = None) -> str:
    ensure_prompt_builder_on_path(settings)
    from prompt_builder import build_zones

    s = settings or Settings()
    cfg = dict(job.prompt_cfg)
    extra = ""
    if job.line_hint:
        extra = f"\nLINEATION NOTE (for segment lineRange consistency): {job.line_hint}\n"
    system, user_text = build_zones(cfg)
    user_text = user_text + extra

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
