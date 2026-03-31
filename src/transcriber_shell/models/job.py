"""Job descriptors for one manuscript crop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TranscribeJob:
    """Single pre-cropped page image and protocol prompt configuration."""

    job_id: str
    image_path: Path
    prompt_cfg: dict[str, Any]
    provider: str = "anthropic"
    # CLI --model overrides TRANSCRIBER_SHELL_MODEL and per-provider defaults.
    model_override: str | None = None
    line_hint: str | None = None  # e.g. "Glyph Machina reports N=12 TextLine elements"


@dataclass
class PipelineResult:
    job_id: str
    lines_xml_path: Path | None
    transcription_yaml_path: Path | None
    text_line_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Populated when the LLM step runs; keys may include input_tokens, output_tokens, total_tokens.
    llm_usage: dict[str, int] | None = None
