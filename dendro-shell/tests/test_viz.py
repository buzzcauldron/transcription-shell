"""Visualization and tile helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from dendro_shell.pipeline import export_all, run_detect
from dendro_shell.project import MeasurePath, Point, RingTick
from dendro_shell.series import WidthSeries
from dendro_shell.viz import (
    extract_ring_tiles,
    render_compare_overlay,
    render_confidence_overlay,
    render_growth_panel,
    render_report_png,
    render_skeleton_plot,
    tiles_contact_sheet,
)


def _series() -> WidthSeries:
    return WidthSeries(
        years=list(range(2000, 2020)),
        widths_um=[80 + (i % 5) * 10 for i in range(20)],
        widths_px=[8.0] * 20,
        flags=["ok"] * 19 + ["missing"],
        sample_code="VIZ01",
    )


def test_skeleton_and_growth_shapes():
    s = _series()
    sk = render_skeleton_plot(s)
    gr = render_growth_panel(s)
    assert sk.size[0] == 900
    assert gr.size[1] >= 200


def test_tiles_and_compare(tmp_path: Path):
    w, h = 400, 120
    img = np.full((h, w), 160, dtype=np.uint8)
    path = MeasurePath(
        id="path0",
        points=[Point(x=10, y=60), Point(x=390, y=60)],
        rings=[
            RingTick(distance_px=100, year=2020, confidence=0.9),
            RingTick(distance_px=200, year=2019, confidence=0.5),
            RingTick(distance_px=300, year=2018, confidence=0.8, flag="missing"),
        ],
    )
    tiles = extract_ring_tiles(img, path, tile=64, half_width=24)
    assert len(tiles) == 3
    sheet = tiles_contact_sheet(tiles, cols=3)
    assert sheet.size[0] > 64
    cmp_img = render_compare_overlay(
        img,
        path.rings,
        [RingTick(distance_px=105, confidence=0.7), RingTick(distance_px=198, confidence=0.6)],
        path,
    )
    assert cmp_img.size[0] == w


def test_export_writes_report(tmp_path: Path):
    w, h = 500, 100
    arr = np.full((h, w), 170, dtype=np.float32)
    xs = np.linspace(40, w - 40, 10)
    xx = np.arange(w)
    for x in xs:
        arr -= 40 * np.exp(-0.5 * ((xx - x) / 2.0) ** 2)[None, :]
    img_path = tmp_path / "c.png"
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(img_path)
    project = run_detect(img_path, sample_code="R1", min_distance_px=10, prominence=0.05, outer_year=2020)
    out = export_all(project, tmp_path / "out")
    assert Path(out["skeleton"]).is_file()
    assert Path(out["report"]).is_file()
    assert Path(out["overlay"]).is_file()
    # confidence overlay works
    ov = render_confidence_overlay(project)
    assert ov.size[0] > 0
    rep = render_report_png(project)
    assert rep.size[1] > ov.size[1]
