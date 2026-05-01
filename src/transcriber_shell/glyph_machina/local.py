"""Local Glyph Machina segmentation via seg.mlmodel — no browser, no network.

Replaces the Playwright website call when gm_htr_repo_path points to a clone of
ideasrule/glyph_machina_public. Uses the same kraken BLLA Python API as
kraken_lineation.py with GM's bundled seg.mlmodel.

Credit: ideasrule/glyph_machina_public (GPL-3.0)
  https://github.com/ideasrule/glyph_machina_public
Training data: mzzhang2014/glyph_machina
  https://huggingface.co/datasets/mzzhang2014/glyph_machina
"""

from __future__ import annotations

from pathlib import Path

from transcriber_shell.config import Settings


class GlyphMachinaLocalError(RuntimeError):
    pass


def fetch_lines_xml_gm_local(
    image_path: Path,
    job_id: str,
    settings: Settings | None = None,
) -> Path:
    """Segment with GM's seg.mlmodel via the kraken Python API.

    Equivalent to running run_segmenter.py but without spawning a subprocess
    and with proper device auto-detection, model caching, and cloud-file fallback.
    """
    s = settings or Settings()

    if not s.gm_htr_repo_path:
        raise GlyphMachinaLocalError(
            "TRANSCRIBER_SHELL_GM_HTR_REPO_PATH must point to a clone of "
            "https://github.com/ideasrule/glyph_machina_public"
        )

    repo = Path(s.gm_htr_repo_path).expanduser().resolve()
    model_path = repo / "seg.mlmodel"
    if not model_path.is_file():
        raise GlyphMachinaLocalError(
            f"seg.mlmodel not found at {model_path}. "
            "Ensure the repo is fully cloned — model files are committed to the repository."
        )

    try:
        from kraken import blla, serialization
    except ImportError as e:
        raise GlyphMachinaLocalError(
            "Kraken is not installed. Install with: pip install 'transcriber-shell[kraken]'"
        ) from e

    from transcriber_shell.kraken_lineation import (
        KrakenLineationError,
        _best_device,
        _checksum_image,
        _ensure_torch_threads,
        _get_blla_seg_params,
        _get_model,
        _open_image,
    )

    _ensure_torch_threads()
    image_path = image_path.expanduser().resolve()
    if not image_path.is_file():
        raise GlyphMachinaLocalError(f"image not found: {image_path}")

    out_dir = (s.artifacts_dir / job_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "source_image.sha256").write_text(
        f"{_checksum_image(image_path)}  {image_path.name}\n", encoding="utf-8"
    )

    try:
        device = _best_device(s.kraken_device)
        model = _get_model(model_path, device)
        im = _open_image(image_path)

        params = _get_blla_seg_params()
        seg_kwargs: dict = {"text_direction": "horizontal-lr", "model": model, "device": device}
        if "threshold" in params:
            seg_kwargs["threshold"] = s.kraken_threshold
        if "min_length" in params:
            seg_kwargs["min_length"] = s.kraken_min_length

        res = blla.segment(im, **seg_kwargs)
        xml_contents = serialization.serialize(
            res,
            image_size=im.size,
            template="pagexml",
            template_source="native",
            processing_steps=[{
                "category": "processing",
                "description": "Baseline and region segmentation (Glyph Machina local, seg.mlmodel)",
                "settings": {
                    "model": "seg.mlmodel",
                    "text_direction": "horizontal-lr",
                    "credit": "ideasrule/glyph_machina_public GPL-3.0 "
                              "https://github.com/ideasrule/glyph_machina_public",
                },
            }],
            sub_line_segmentation=True,
        )
        out_xml = out_dir / "lines.xml"
        out_xml.write_text(xml_contents, encoding="utf-8")
        if not out_xml.stat().st_size:
            raise GlyphMachinaLocalError("GM local segmentation produced empty lines.xml")
        return out_xml
    except KrakenLineationError as e:
        raise GlyphMachinaLocalError(str(e)) from e
    except Exception as e:  # noqa: BLE001
        # Device errors (CUDA unavailable, OOM), model load failures, etc. — convert so
        # workflow.py can fall back to the website rather than propagating uncaught.
        raise GlyphMachinaLocalError(f"Local segmentation error ({type(e).__name__}): {e}") from e
