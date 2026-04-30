"""HTR using the Glyph Machina pipeline (line-image generator + HTR net).

Software credit:
  ideasrule/glyph_machina_public — Glyph Machina
  https://github.com/ideasrule/glyph_machina_public
  (all rights reserved by the respective authors; used here as an optional backend)

Training data credit:
  mzzhang2014/glyph_machina (Hugging Face Datasets)
  https://huggingface.co/datasets/mzzhang2014/glyph_machina

Requires: gm_htr_repo_path in Settings pointing to a clone of glyph_machina_public.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from transcriber_shell.htr.base import HtrResult


def run_gm_htr(
    image_path: Path,
    lines_xml_path: Path,
    *,
    repo_path: Path,
    device: str = "cpu",
) -> HtrResult:
    """Run GM line-image generator then HTR net; return concatenated predictions."""
    repo_path = Path(repo_path).expanduser().resolve()
    run_line_gen = repo_path / "run_line_image_generator.py"
    run_htr = repo_path / "run_htr.py"
    for p in (run_line_gen, run_htr):
        if not p.is_file():
            raise FileNotFoundError(
                f"Glyph Machina script not found: {p}. "
                "Set TRANSCRIBER_SHELL_GM_HTR_REPO_PATH to the repo root."
            )

    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ts_gm_htr_") as tmp:
        tmp_dir = Path(tmp)
        line_images_dir = tmp_dir / "line_images"
        line_images_dir.mkdir()
        htr_out = tmp_dir / "htr_output.txt"

        # Stage 1: generate per-line images from the PageXML
        gen_cmd = [
            sys.executable, str(run_line_gen),
            "--input-image", str(image_path),
            "--input-xml", str(lines_xml_path),
            "--output-dir", str(line_images_dir),
        ]
        gen_result = subprocess.run(gen_cmd, capture_output=True, text=True)
        if gen_result.returncode != 0:
            raise RuntimeError(
                f"GM line-image generator failed (exit {gen_result.returncode}): "
                f"{gen_result.stderr.strip()}"
            )
        if gen_result.stderr.strip():
            warnings.append(f"GM line-generator: {gen_result.stderr.strip()[:200]}")

        line_files = sorted(line_images_dir.glob("*.png")) + sorted(line_images_dir.glob("*.jpg"))
        if not line_files:
            return HtrResult(
                text="", backend="gm-htr", line_count=0,
                warnings=["GM line-image generator produced no line images."],
            )

        # Stage 2: run HTR net
        htr_cmd = [
            sys.executable, str(run_htr),
            "--input-dir", str(line_images_dir),
            "--output-file", str(htr_out),
            "--device", device,
        ]
        htr_result = subprocess.run(htr_cmd, capture_output=True, text=True)
        if htr_result.returncode != 0:
            raise RuntimeError(
                f"GM HTR net failed (exit {htr_result.returncode}): "
                f"{htr_result.stderr.strip()}"
            )
        if htr_result.stderr.strip():
            warnings.append(f"GM HTR: {htr_result.stderr.strip()[:200]}")

        text = htr_out.read_text(encoding="utf-8") if htr_out.is_file() else ""
        lines = [l for l in text.splitlines() if l.strip()]
        return HtrResult(
            text="\n".join(lines),
            backend="gm-htr",
            line_count=len(lines),
            warnings=warnings,
        )
