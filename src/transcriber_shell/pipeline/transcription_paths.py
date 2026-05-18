"""Paths for pipeline outputs under artifacts."""

from __future__ import annotations

from pathlib import Path


def transcription_yaml_path(artifacts_dir: Path, job_id: str, image_path: Path) -> Path:
    """LLM output file: ``artifacts/<job_id>/<image_stem>_transcription.yaml``."""
    name = f"{image_path.stem}_transcription.yaml"
    return (artifacts_dir / job_id / name).resolve()


def transcription_txt_path(artifacts_dir: Path, job_id: str, image_path: Path) -> Path:
    """Plain-text companion: ``artifacts/<job_id>/<image_stem>_transcription.txt``."""
    name = f"{image_path.stem}_transcription.txt"
    return (artifacts_dir / job_id / name).resolve()


def lines_xml_canonical_path(artifacts_dir: Path, job_id: str) -> Path:
    """Default lines XML path produced by the lineation backends.

    All three backends (kraken, mask, glyph_machina) write to
    ``artifacts/<job_id>/lines.xml`` — this is the path the pipeline can
    reuse to skip re-running lineation when the file is already present
    and non-empty.
    """
    return (artifacts_dir / job_id / "lines.xml").resolve()
