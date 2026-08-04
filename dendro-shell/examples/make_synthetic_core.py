#!/usr/bin/env python3
"""Generate a synthetic core image with known ring positions for demos/tests."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image


def make_core(
    out_dir: Path,
    *,
    width: int = 900,
    height: int = 180,
    n_rings: int = 24,
    seed: int = 0,
) -> Path:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    img = np.zeros((height, width), dtype=np.float32)
    # base wood texture
    img += 160 + 12 * rng.standard_normal((height, width))
    xs = np.linspace(40, width - 40, n_rings)
    for x in xs:
        # dark latewood band
        xx = np.arange(width)
        band = np.exp(-0.5 * ((xx - x) / 2.2) ** 2)
        img -= 55 * band[None, :]
    img = np.clip(img, 0, 255).astype(np.uint8)
    # mild horizontal grain
    for y in range(height):
        img[y] = np.clip(img[y] + (y % 3) - 1, 0, 255)

    path = out_dir / "synthetic_core.png"
    Image.fromarray(img, mode="L").save(path)
    meta = {
        "image": str(path.name),
        "ring_x": [float(x) for x in xs],
        "n_rings": n_rings,
        "note": "Vertical latewood bands; measure along mid-height horizontal path",
    }
    (out_dir / "synthetic_core_meta.json").write_text(json.dumps(meta, indent=2))
    return path


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    p = make_core(root)
    print(p)
