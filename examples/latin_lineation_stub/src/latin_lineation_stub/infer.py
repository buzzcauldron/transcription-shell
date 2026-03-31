"""Stub `predict_masks` for testing the mask lineation plugin boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def predict_masks(image_path: Path, settings: Any) -> np.ndarray:
    """Return a synthetic (L, H, W) float mask grid (not trained inference).

    Real plugins should load ``getattr(settings, \"mask_weights_path\", None)`` or
    custom env vars, run the model on ``image_path``, and return shape (L, H, W).
    """
    _ = getattr(settings, "mask_device", None)
    _wpath = getattr(settings, "mask_weights_path", None)
    if _wpath is not None:
        # Stub does not load checkpoints; real code would use this path.
        pass

    with Image.open(image_path) as im:
        w, h = im.size
    # Coarse grid (~1/16 of page); several horizontal strip masks (multi-line stub)
    gw = max(8, w // 16)
    gh = max(8, h // 16)
    n_lines = min(3, max(1, gh // 6))
    pred = np.zeros((n_lines, gh, gw), dtype=np.float32)
    for li in range(n_lines):
        y = int((li + 1) * gh / (n_lines + 1))
        pred[li, y, :] = 1.0
    return pred
