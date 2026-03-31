"""Paths for pipeline outputs under artifacts."""

from __future__ import annotations

from pathlib import Path


def transcription_yaml_path(artifacts_dir: Path, job_id: str, image_path: Path) -> Path:
    """LLM output file: ``artifacts/<job_id>/<image_stem>_transcription.yaml``."""
    name = f"{image_path.stem}_transcription.yaml"
    return (artifacts_dir / job_id / name).resolve()
