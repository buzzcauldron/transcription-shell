"""Discover images and run the pipeline for each (sequential)."""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path
from typing import Any

from transcriber_shell.config import Settings
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.pipeline.run import run_pipeline

IMAGE_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
)


def sanitize_job_id(stem: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("._-")
    return (s[:120] if s else "job")


def discover_images(path_or_glob: str) -> list[Path]:
    raw = path_or_glob.strip()
    if any(ch in raw for ch in "*?["):
        paths = [Path(p) for p in sorted(glob.glob(raw, recursive=True))]
        return [p for p in paths if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    p = Path(raw).expanduser().resolve()
    if p.is_file():
        return [p] if p.suffix.lower() in IMAGE_SUFFIXES else []
    if p.is_dir():
        out = [
            x
            for x in p.iterdir()
            if x.is_file() and x.suffix.lower() in IMAGE_SUFFIXES
        ]
        return sorted(out)
    return []


def resolve_lines_xml_for_image(
    image: Path,
    *,
    skip_gm: bool,
    lines_xml: Path | None,
    lines_xml_dir: Path | None,
    n_images: int,
) -> Path | None:
    """Return path to lines XML when skip_gm; otherwise None (lineation backend fetches per job)."""
    if not skip_gm:
        return None
    if lines_xml_dir is not None:
        candidate = lines_xml_dir / f"{image.stem}.xml"
        if candidate.is_file():
            return candidate.resolve()
        raise FileNotFoundError(
            f"Skip Glyph Machina + batch: need one lines XML per image stem. "
            f"Missing file: {candidate} (under --lines-xml-dir). "
            f"Expected filename '{image.stem}.xml' next to image '{image.name}'."
        )
    if lines_xml is not None:
        if n_images != 1:
            raise ValueError(
                "Skip Glyph Machina: --lines-xml applies only when there is exactly one image. "
                "For multiple images use --lines-xml-dir with <image_stem>.xml for each page."
            )
        return lines_xml.resolve()
    raise ValueError(
        "Skip Glyph Machina requires --lines-xml (single image) or --lines-xml-dir (folder of per-page XML files)."
    )


def run_batch(
    images: list[Path],
    prompt_cfg: dict[str, Any],
    *,
    provider: str,
    model_override: str | None,
    skip_gm: bool,
    lines_xml: Path | None,
    lines_xml_dir: Path | None,
    xsd_path: Path | None,
    require_text_line: bool,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Run pipeline for each image; return report rows (dicts)."""
    s = settings or Settings()
    n = len(images)
    rows: list[dict[str, Any]] = []
    for image in images:
        job_id = sanitize_job_id(image.stem)
        lx: Path | None = None
        try:
            if skip_gm:
                lx = resolve_lines_xml_for_image(
                    image,
                    skip_gm=True,
                    lines_xml=lines_xml,
                    lines_xml_dir=lines_xml_dir,
                    n_images=n,
                )
        except (FileNotFoundError, ValueError) as e:
            rows.append(
                {
                    "job_id": job_id,
                    "image": str(image),
                    "ok": False,
                    "errors": [str(e)],
                    "text_line_count": 0,
                    "lines_xml": None,
                    "transcription_yaml": None,
                }
            )
            continue

        job = TranscribeJob(
            job_id=job_id,
            image_path=image.resolve(),
            prompt_cfg=prompt_cfg,
            provider=provider,
            model_override=model_override,
        )
        res = run_pipeline(
            job,
            skip_gm=skip_gm,
            lines_xml_path=lx,
            xsd_path=xsd_path,
            require_text_line=require_text_line,
            settings=s,
        )
        row: dict[str, Any] = {
            "job_id": res.job_id,
            "image": str(image),
            "ok": len(res.errors) == 0,
            "errors": res.errors,
            "warnings": res.warnings,
            "text_line_count": res.text_line_count,
            "lines_xml": str(res.lines_xml_path) if res.lines_xml_path else None,
            "transcription_yaml": str(res.transcription_yaml_path)
            if res.transcription_yaml_path
            else None,
        }
        rows.append(row)
    return rows


def write_batch_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
