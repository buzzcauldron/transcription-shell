"""Kraken BLLA → PageXML lines file. Install: pip install 'transcriber-shell[kraken]'."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from transcriber_shell.config import Settings


class KrakenLineationError(RuntimeError):
    pass


def _checksum_image(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


_model = None
_model_path_loaded: Path | None = None


def _get_model(model_path: Path, device: str):
    global _model, _model_path_loaded
    mp = model_path.resolve()
    if _model is not None and _model_path_loaded == mp:
        return _model
    try:
        from kraken.lib.vgsl import TorchVGSLModel
    except ImportError as e:
        raise KrakenLineationError(
            "Kraken is not installed. Install with: pip install 'transcriber-shell[kraken]'"
        ) from e
    model = TorchVGSLModel.load_model(str(mp))
    model.to(device)
    _model = model
    _model_path_loaded = mp
    return model


def fetch_lines_xml_kraken(
    image_path: Path,
    job_id: str,
    settings: Settings | None = None,
) -> Path:
    """Segment with BLLA, serialize PageXML under ``artifacts_dir/job_id/lines.xml``."""
    s = settings or Settings()
    if not s.kraken_model_path:
        raise KrakenLineationError(
            "Kraken lineation requires TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH to a .mlmodel file"
        )
    image_path = image_path.expanduser().resolve()
    if not image_path.is_file():
        raise KrakenLineationError(f"image not found: {image_path}")

    out_dir = (s.artifacts_dir / job_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = out_dir / "source_image.sha256"
    meta.write_text(f"{_checksum_image(image_path)}  {image_path.name}\n", encoding="utf-8")

    model_path = s.kraken_model_path.expanduser().resolve()
    if not model_path.is_file():
        raise KrakenLineationError(f"Kraken model not found: {model_path}")

    try:
        from kraken import blla
        from kraken import serialization
    except ImportError as e:
        raise KrakenLineationError(
            "Kraken is not installed. Install with: pip install 'transcriber-shell[kraken]'"
        ) from e

    device = s.kraken_device
    model = _get_model(model_path, device)
    im = Image.open(image_path)
    res = blla.segment(
        im,
        text_direction="horizontal-lr",
        model=model,
        device=device,
        threshold=s.kraken_threshold,
        min_length=s.kraken_min_length,
    )
    model_fn = model_path.name
    credit = s.lineation_credit_repo_url
    xml_contents = serialization.serialize(
        res,
        image_size=im.size,
        template="pagexml",
        template_source="native",
        processing_steps=[
            {
                "category": "processing",
                "description": "Baseline and region segmentation (Kraken BLLA)",
                "settings": {
                    "model": model_fn,
                    "text_direction": "horizontal-lr",
                    "credit": credit,
                },
            }
        ],
        sub_line_segmentation=True,
    )
    out_xml = out_dir / "lines.xml"
    out_xml.write_text(xml_contents, encoding="utf-8")
    if not out_xml.stat().st_size:
        raise KrakenLineationError("Kraken produced empty lines.xml")
    return out_xml
