"""Locate vendored transcription-protocol for imports and subprocess."""

from __future__ import annotations

import sys
from pathlib import Path

from transcriber_shell.config import Settings


def ensure_protocol_benchmark_on_path(settings: Settings | None = None) -> Path:
    """Add vendor/transcription-protocol/benchmark to sys.path. Returns benchmark dir."""
    s = settings or Settings()
    root = s.resolved_protocol_root()
    bench = root / "benchmark"
    if not (bench / "validate_schema.py").is_file():
        raise FileNotFoundError(
            f"transcription-protocol benchmark not found at {bench}. "
            "Add submodule: git submodule update --init vendor/transcription-protocol"
        )
    p = str(bench.resolve())
    if p not in sys.path:
        sys.path.insert(0, p)
    return bench


def ensure_prompt_builder_on_path(settings: Settings | None = None) -> Path:
    """Same benchmark path; prompt_builder lives there."""
    return ensure_protocol_benchmark_on_path(settings)
