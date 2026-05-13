"""Illustration masking via the eynollah SBB/eynollah-image-extraction SavedModel.

The canonical logic; scripts/latin_ms/mask_illustrations.py delegates here.

Class mapping (SBB model):
  0 = background  1 = text  2 = illustration  3 = separator  4 = marginalia
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

MODEL_INPUT_SIZE = 672
_DEFAULT_MODEL = Path.home() / "eynollah_models" / "extract_images"


def _force_cpu() -> None:
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")


def load_model(model_path: Path):
    """Load the TF SavedModel and return its serving_default signature."""
    _force_cpu()
    try:
        import tensorflow as tf
    except ImportError as e:
        raise ImportError("TensorFlow required for illustration masking: pip install tensorflow") from e
    tf.config.set_visible_devices([], "GPU")
    m = tf.saved_model.load(str(model_path))
    return m.signatures["serving_default"]


def segment_image(infer, img: Image.Image) -> np.ndarray:
    """Return (H_orig, W_orig) integer class map (0–4)."""
    import tensorflow as tf

    orig_w, orig_h = img.size
    img_r = img.resize((MODEL_INPUT_SIZE, MODEL_INPUT_SIZE), Image.BILINEAR)
    arr = np.array(img_r.convert("RGB"), dtype=np.float32) / 255.0
    out = infer(input_1=tf.constant(arr[np.newaxis]))
    pred = list(out.values())[0].numpy()[0]          # (672, 672, 5)
    seg_small = np.argmax(pred, axis=-1).astype(np.uint8)
    seg_orig = Image.fromarray(seg_small, mode="L").resize((orig_w, orig_h), Image.NEAREST)
    return np.array(seg_orig, dtype=np.uint8)


def dilate_mask(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask
    try:
        from scipy.ndimage import binary_dilation
        struct = np.ones((px * 2 + 1, px * 2 + 1), dtype=bool)
        return binary_dilation(mask, structure=struct).astype(np.uint8)
    except ImportError:
        from numpy.lib.stride_tricks import sliding_window_view
        padded = np.pad(mask, px, mode="edge")
        windows = sliding_window_view(padded, (px * 2 + 1, px * 2 + 1))
        return (windows.max(axis=(-2, -1)) > 0).astype(np.uint8)


def apply_mask(
    img: Image.Image,
    seg: np.ndarray,
    classes: list[int],
    dilate_px: int = 8,
) -> Image.Image:
    """White out pixels belonging to any of the given segmentation classes."""
    combined = np.zeros(seg.shape, dtype=np.uint8)
    for c in classes:
        combined |= (seg == c).astype(np.uint8)
    if dilate_px > 0:
        combined = dilate_mask(combined, dilate_px)
    arr = np.array(img.convert("RGB"))
    arr[combined == 1] = 255
    return Image.fromarray(arr)


def mask_file(
    src: Path,
    infer,
    *,
    out_dir: Path | None = None,
    suffix: str = "_masked",
    in_place: bool = False,
    classes: list[int] | None = None,
    dilate_px: int = 8,
) -> tuple[str, str]:
    """Mask one image. Returns (status, message)."""
    if classes is None:
        classes = [2]
    if in_place:
        dst = src
    else:
        base = out_dir if out_dir else src.parent
        dst = base / (src.stem + suffix + src.suffix)

    try:
        img = Image.open(src)
        seg = segment_image(infer, img)
        masked = apply_mask(img, seg, classes, dilate_px)
        save_kwargs: dict = {}
        if dst.suffix.lower() in (".jpg", ".jpeg"):
            save_kwargs = {"quality": 92, "optimize": True}
        masked.save(dst, **save_kwargs)
        masked_px = int(sum((seg == c).sum() for c in classes))
        pct = masked_px / seg.size * 100
        return "ok", f"{src.name} → {dst.name}  {masked_px} px masked ({pct:.1f}%)"
    except Exception as exc:
        return "error", f"{src.name}: {exc}"
