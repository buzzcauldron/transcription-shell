"""Kraken BLLA → PageXML lines file. Install: pip install 'transcriber-shell[kraken]'."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import warnings
from pathlib import Path

# coremltools is loaded as a transitive dep of kraken; on Apple Silicon it warns
# once per .mlmodel load that the CoreML representation can't be compiled (input
# shape mismatch with MLMultiArray). Kraken uses the torch weights path either way,
# so the warning is harmless noise — suppress it.
warnings.filterwarnings(
    "ignore",
    message=r"You will not be able to run predict\(\) on this Core ML model.*",
    category=RuntimeWarning,
)

import threading

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
# Serializes blla.segment calls across batch worker threads.  The model is a
# module-level singleton; concurrent forward passes on one CUDA model are not
# thread-safe and cause VRAM OOM on a GPU shared with Ollama.
_inference_lock = threading.Lock()


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
    # Releasing the outgoing model matters on a GPU shared with Ollama: without
    # this, switching segmentation models leaves the previous weights resident and
    # the next large page OOMs.
    if _model is not None:
        _model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    model = TorchVGSLModel.load_model(str(mp))
    model.to(device)
    # kraken's blla.segment does NOT put the net in eval mode itself (checked
    # against 7.0.2), so any dropout/batchnorm layers would otherwise run in
    # training mode and make segmentation non-deterministic between calls.
    try:
        model.eval()
    except AttributeError:
        # TorchVGSLModel is a wrapper; fall back to the inner nn.Module.
        inner = getattr(model, "nn", None)
        if inner is not None and hasattr(inner, "eval"):
            inner.eval()

    _model = model
    _model_path_loaded = mp
    _model_device_loaded = device
    return model


# ── Image loading ─────────────────────────────────────────────────────────────

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


_warned_ignored_settings = False


def _warn_ignored_seg_settings(s: Settings, params: frozenset[str]) -> None:
    """Warn once if a configured segmentation knob is not supported by kraken."""
    global _warned_ignored_settings
    if _warned_ignored_settings:
        return
    # Only complain about values the operator actually SET. Both fields carry
    # non-None defaults, so testing against None would fire this warning on every
    # run of every machine and train people to ignore it.
    explicit = getattr(s, "model_fields_set", set()) or set()
    ignored = []
    if "threshold" not in params and "kraken_threshold" in explicit:
        ignored.append(f"kraken_threshold={s.kraken_threshold}")
    if "min_length" not in params and "kraken_min_length" in explicit:
        ignored.append(f"kraken_min_length={s.kraken_min_length}")
    if ignored:
        warnings.warn(
            "[transcriber-shell] installed kraken's blla.segment does not accept "
            + ", ".join(ignored)
            + " -- these settings have NO EFFECT on this version. Remove them or "
            "pin a kraken that supports them.",
            stacklevel=3,
        )
    _warned_ignored_settings = True


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

    model_path = s.kraken_model_path.expanduser().resolve()
    if sys.platform != "darwin" and "/Users/" in str(model_path):
        raise KrakenLineationError(
            f"refusing Mac Kraken path on {sys.platform}: {model_path}"
        )
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
    else:
        # kraken 7.x dropped `threshold` and `min_length` from blla.segment. The
        # conditionals above correctly avoid a TypeError, but silently dropping a
        # configured value is worse than failing: the operator sets
        # kraken_min_length, sees no error, and believes it took effect. Say so.
        _warn_ignored_seg_settings(s, params)

    # Surface segmentation failures instead of logging and returning a degraded
    # result. kraken defaults raise_on_error=False, which is why a page could
    # previously yield a near-empty lines.xml with nothing in our logs to explain
    # it -- the error went to kraken's logger and the pipeline carried on.
    if "raise_on_error" in params:
        seg_kwargs["raise_on_error"] = True

    # Mixed precision, but only on CUDA. kraken threads `autocast` down to
    # compute_segmentation_map; it is a real speed/VRAM win on the 4090 and a
    # loss (or unsupported) on CPU, and MPS autocast is still unreliable.
    if "autocast" in params and device.startswith("cuda") and s.kraken_autocast:
        seg_kwargs["autocast"] = True

    with _inference_lock:
        # blla.segment does not wrap its forward pass, so without this every
        # segmentation builds an autograd graph it never uses -- wasted time and
        # VRAM on a GPU we already share with Ollama.
        try:
            import torch
            ctx = torch.inference_mode()
        except Exception:
            from contextlib import nullcontext
            ctx = nullcontext()
        with ctx:
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

    # A batch run segments tens of thousands of pages in one process; an
    # unclosed PIL image per page holds its decoded buffer until GC notices.
    try:
        im.close()
    except Exception:
        pass

    from transcriber_shell.xml_tools.tag_margins import tag_margin_lines
    tag_margin_lines(out_xml)

    return out_xml
