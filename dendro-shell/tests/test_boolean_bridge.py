"""Boolean ring matching across synthetic cracks."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from dendro_shell.detect.boolean_bridge import (
    boolean_same_ring,
    detect_break_mask,
    detect_rings_boolean_bridge,
)
from dendro_shell.pipeline import run_detect
from dendro_shell.project import Point


def _cracked_disc(path: Path, *, n_rings: int = 18, crack_width: int = 10) -> Path:
    """Concentric rings with a bright radial crack (break)."""
    size = 420
    cx = cy = size // 2
    img = np.full((size, size), 210, dtype=np.uint8)
    yy, xx = np.ogrid[:size, :size]
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    for rad in np.linspace(20, 180, n_rings):
        band = (r > rad - 1.2) & (r < rad + 1.2)
        img[band] = 40
    # Radial crack (bright gap) from pith to edge at ~30 degrees
    ang = np.deg2rad(30)
    for t in range(15, 190):
        x = int(cx + t * np.cos(ang))
        y = int(cy + t * np.sin(ang))
        cv2.circle(img, (x, y), crack_width // 2, 245, -1)
    # Mild noise
    rng = np.random.default_rng(0)
    img = np.clip(img.astype(np.int16) + rng.integers(-8, 9, img.shape), 0, 255).astype(np.uint8)
    Image.fromarray(img).save(path)
    return path


def test_boolean_same_ring_predicate():
    assert boolean_same_ring(100.0, 102.0, 3.0)
    assert not boolean_same_ring(100.0, 110.0, 3.0)


def test_break_mask_finds_crack(tmp_path: Path):
    img_path = _cracked_disc(tmp_path / "c.png")
    gray = np.asarray(Image.open(img_path).convert("L"))
    pith = Point(x=210, y=210)
    mask = detect_break_mask(gray, pith=pith)
    assert mask.shape == gray.shape
    assert mask.max() > 0
    # Crack corridor should light up near 30°
    x = int(210 + 100 * np.cos(np.deg2rad(30)))
    y = int(210 + 100 * np.sin(np.deg2rad(30)))
    assert mask[y - 5 : y + 6, x - 5 : x + 6].max() > 0


def test_boolean_bridge_recovers_rings(tmp_path: Path):
    img_path = _cracked_disc(tmp_path / "c.png", n_rings=16)
    # Diameter path that crosses the crack
    pith = Point(x=210, y=210)
    ang = np.deg2rad(30)
    path = [
        Point(x=210 - 180 * np.cos(ang), y=210 - 180 * np.sin(ang)),
        pith,
        Point(x=210 + 180 * np.cos(ang), y=210 + 180 * np.sin(ang)),
    ]
    res = detect_rings_boolean_bridge(
        Image.open(img_path),
        path,
        pith=pith,
        preset="sanded_core",
        close_px=18,
    )
    assert len(res.rings) >= 8
    # At least one tick marked bridged or uncertain when path hits the crack
    notes = [r.note for r in res.rings]
    flags = [r.flag for r in res.rings]
    assert any(n in ("bridged", "matched", "polar") for n in notes)
    assert any(f in ("ok", "uncertain") for f in flags)


def test_pipeline_boolean_method(tmp_path: Path):
    img_path = _cracked_disc(tmp_path / "c.png", n_rings=14)
    project = run_detect(
        img_path,
        method="boolean",
        sample_type="disc",
        preset="sanded_core",
        outer_year=2020,
        sample_code="BRK01",
        auto=False,
    )
    assert project.detect_method == "boolean"
    assert len(project.paths[0].rings) >= 6
    assert "boolean_bridge" in project.notes
