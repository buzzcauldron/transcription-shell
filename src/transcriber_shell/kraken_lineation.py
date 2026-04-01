"""Kraken BLLA → PageXML lines file. Install: pip install 'transcriber-shell[kraken]'."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from transcriber_shell.config import Settings


class KrakenLineationError(RuntimeError):
    pass


# ── Hardware / power helpers ─────────────────────────────────────────────────

def _best_device(configured: str) -> str:
    """Resolve configured device to the fastest available given hardware + power state.

    - MPS (Apple Silicon) is used when available; it's faster than CPU and more
      power-efficient for inference, so we use it on battery too.
    - CUDA is trusted as-is when explicitly configured.
    - 'cpu' triggers auto-detection; any other explicit value is returned unchanged.
    """
    if configured not in ("cpu", "auto"):
        return configured
    try:
        import torch
        if torch.backends.mps.is_available() and torch.backends.mps.is_built():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _configure_torch_threads() -> None:
    """Set PyTorch CPU thread count based on core count and power state.

    Plugged in → use all physical cores (up to 8).
    On battery → use half the cores to conserve power.
    Called once at module load; safe to call multiple times (idempotent result).
    """
    try:
        import torch
        try:
            import psutil
            bat = psutil.sensors_battery()
            plugged = bat is None or bat.power_plugged
        except Exception:
            plugged = True
        cpu_count = os.cpu_count() or 4
        threads = min(cpu_count, 8) if plugged else max(2, cpu_count // 2)
        torch.set_num_threads(threads)
    except Exception:
        pass


_torch_threads_configured = False


def _ensure_torch_threads() -> None:
    global _torch_threads_configured
    if not _torch_threads_configured:
        _configure_torch_threads()
        _torch_threads_configured = True


# ── Module-level caches ───────────────────────────────────────────────────────

_model = None
_model_path_loaded: Path | None = None
_model_device_loaded: str | None = None
_blla_seg_params: frozenset[str] | None = None


def _get_blla_seg_params() -> frozenset[str]:
    global _blla_seg_params
    if _blla_seg_params is None:
        import inspect
        from kraken import blla
        _blla_seg_params = frozenset(inspect.signature(blla.segment).parameters)
    return _blla_seg_params


def _get_model(model_path: Path, device: str):
    global _model, _model_path_loaded, _model_device_loaded
    mp = model_path.resolve()
    if _model is not None and _model_path_loaded == mp and _model_device_loaded == device:
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
    _model_device_loaded = device
    return model


# ── Image loading ─────────────────────────────────────────────────────────────

def _checksum_image(path: Path) -> str:
    try:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()[:16]
    except (OSError, TimeoutError):
        return "unavailable"


def _open_image(image_path: Path) -> Image.Image:
    """Open and fully load an image, falling back to a local tmp copy for cloud files."""
    try:
        im = Image.open(image_path)
        im.load()
        return im
    except (OSError, TimeoutError):
        pass
    # Cloud-only file (OneDrive / iCloud): copy to local tmp first.
    suffix = image_path.suffix or ".jpg"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            shutil.copy2(image_path, tmp_path)
        except (OSError, TimeoutError) as e:
            raise KrakenLineationError(
                f"Image file could not be read — it may be a cloud-only placeholder "
                f"(OneDrive / iCloud). Open the file in Finder to force a download, "
                f"then retry. ({image_path.name}: {e})"
            ) from e
        im = Image.open(tmp_path)
        im.load()
        return im
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


# ── Main entry point ──────────────────────────────────────────────────────────

def fetch_lines_xml_kraken(
    image_path: Path,
    job_id: str,
    settings: Settings | None = None,
) -> Path:
    """Segment with BLLA, serialize PageXML under ``artifacts_dir/job_id/lines.xml``."""
    _ensure_torch_threads()

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
