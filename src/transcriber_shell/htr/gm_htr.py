"""HTR using the Glyph Machina pipeline (run_line_image_generator.py + run_htr.py).

run_htr.py hardcodes device="cuda:0" and loads best_HTR.net from the repo root (CWD).
A NVIDIA GPU is required; the upstream README notes CPU is possible but unusably slow.

Software credit:
  ideasrule/glyph_machina_public — Glyph Machina (GPL-3.0)
  https://github.com/ideasrule/glyph_machina_public

Training data credit:
  mzzhang2014/glyph_machina (Hugging Face Datasets)
  https://huggingface.co/datasets/mzzhang2014/glyph_machina
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from transcriber_shell.htr.base import HtrResult


def _xml_namespace(element: ET.Element) -> str:
    m = re.match(r"\{.*\}", element.tag)
    return m.group(0)[1:-1] if m else ""


def _copy_xml_abs_image(src: Path, dst: Path, image_path: Path) -> None:
    """Write copy of PageXML to dst with imageFilename replaced by the absolute image path.

    run_line_image_generator.py resolves imageFilename relative to the XML's directory,
    so we set it to an absolute path to decouple the temp copy from the source location.
    """
    tree = ET.parse(str(src))
    root = tree.getroot()
    ns_uri = _xml_namespace(root)
    ns = {"ns": ns_uri}
    ET.register_namespace("", ns_uri)
    page = root.find("ns:Page", ns)
    if page is not None:
        page.set("imageFilename", str(image_path))
    tree.write(str(dst), xml_declaration=True, encoding="utf-8")


def _extract_predictions(xml_path: Path) -> list[str]:
    """Return per-line TextEquiv/Unicode texts written in-place by run_htr.py."""
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    ns = {"ns": _xml_namespace(root)}
    texts: list[str] = []
    for text_region in root.findall(".//ns:TextRegion", ns):
        for text_line in text_region.findall(".//ns:TextLine", ns):
            if text_line.get("custom") == "type {type:margin;}":
                continue
            text_equiv = text_line.find("ns:TextEquiv", ns)
            if text_equiv is not None:
                unicode_elem = text_equiv.find("ns:Unicode", ns)
                if unicode_elem is not None and unicode_elem.text:
                    texts.append(unicode_elem.text.strip())
    return texts


def _best_torch_device() -> str:
    """Return the best available torch device: cuda:0 > mps > cpu."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda:0"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def run_gm_htr(
    image_path: Path,
    lines_xml_path: Path,
    *,
    repo_path: Path,
    device: str = "auto",
) -> HtrResult:
    """Run GM line-image generator then HTR net; return concatenated predictions.

    run_htr.py hardcodes cuda:0; we patch the device line in a temp copy so the
    model can also run on Apple Silicon (mps) or CPU.  Pass device="auto" (default)
    to pick the best available device automatically.  best_HTR.net is loaded from
    repo_path (the script's CWD).
    """
    if device == "auto":
        device = _best_torch_device()

    repo_path = Path(repo_path).expanduser().resolve()
    image_path = Path(image_path).expanduser().resolve()
    lines_xml_path = Path(lines_xml_path).expanduser().resolve()

    run_line_gen = repo_path / "run_line_image_generator.py"
    run_htr_script = repo_path / "run_htr.py"
    htr_net = repo_path / "best_HTR.net"

    for p in (run_line_gen, run_htr_script, htr_net):
        if not p.is_file():
            raise FileNotFoundError(
                f"Glyph Machina file not found: {p}. "
                "Set TRANSCRIBER_SHELL_GM_HTR_REPO_PATH to the cloned repo root "
                "(https://github.com/ideasrule/glyph_machina_public)."
            )

    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ts_gm_htr_") as tmp:
        tmp_dir = Path(tmp)
        tmp_xml = tmp_dir / lines_xml_path.name

        # Set imageFilename to absolute path so the generator finds the source image
        # regardless of where the temp dir lives.
        _copy_xml_abs_image(lines_xml_path, tmp_xml, image_path)

        # Stage 1: generate per-line images into the same directory as tmp_xml
        gen = subprocess.run(
            [sys.executable, str(run_line_gen), str(tmp_xml)],
            capture_output=True,
            text=True,
        )
        if gen.returncode != 0:
            raise RuntimeError(
                f"GM line-image generator failed (exit {gen.returncode}): "
                f"{gen.stderr.strip()}"
            )
        if gen.stderr.strip():
            warnings.append(f"GM line-generator: {gen.stderr.strip()[:300]}")

        line_images = sorted(tmp_dir.glob("line_*.png"))
        if not line_images:
            return HtrResult(
                text="",
                backend="gm-htr",
                line_count=0,
                warnings=["GM line-image generator produced no line images."],
            )

        # Stage 2: HTR — best_HTR.net is loaded from CWD (repo_path); predictions are
        # written back into tmp_xml in-place.  When device is not cuda:0 we write a
        # patched copy of run_htr.py into tmp so upstream isn't modified.
        if device == "cuda:0":
            htr_script_to_run = run_htr_script
        else:
            patched_src = run_htr_script.read_text(encoding="utf-8")
            patched_src = patched_src.replace(
                'device = "cuda:0"', f'device = "{device}"', 1
            )
            htr_script_to_run = tmp_dir / "run_htr_patched.py"
            htr_script_to_run.write_text(patched_src, encoding="utf-8")

        htr = subprocess.run(
            [sys.executable, str(htr_script_to_run), str(tmp_xml)],
            capture_output=True,
            text=True,
            cwd=str(repo_path),
        )
        if htr.returncode != 0:
            raise RuntimeError(
                f"GM HTR failed (exit {htr.returncode}): {htr.stderr.strip()}"
            )
        if htr.stderr.strip():
            warnings.append(f"GM HTR: {htr.stderr.strip()[:300]}")

        texts = _extract_predictions(tmp_xml)
        if not texts:
            warnings.append("GM HTR produced no text predictions (no TextEquiv/Unicode found).")

        return HtrResult(
            text="\n".join(texts),
            backend="gm-htr",
            line_count=len(texts),
            warnings=warnings,
        )
