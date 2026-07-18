"""Geometry, classical detect, and rwl roundtrip tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from dendro_shell.crossdate import correlate_against_reference
from dendro_shell.detect.classical import detect_rings_along_path
from dendro_shell.export.rwl import read_rwl, write_rwl
from dendro_shell.geometry import (
    calibrate_scale,
    micrometers_per_pixel,
    path_length,
    polar_unwrap,
    resample_path,
)
from dendro_shell.pipeline import export_all, run_detect
from dendro_shell.preprocess import preprocess_gray
from dendro_shell.project import MeasurePath, Point, RingTick
from dendro_shell.series import (
    WidthSeries,
    assign_years,
    build_width_series,
    incline_corrected_widths,
)


def _synthetic_core(tmp_path: Path, n_rings: int = 18) -> Path:
    w, h = 700, 140
    img = np.full((h, w), 170, dtype=np.float32)
    xs = np.linspace(50, w - 50, n_rings)
    xx = np.arange(w)
    for x in xs:
        img -= 50 * np.exp(-0.5 * ((xx - x) / 2.0) ** 2)[None, :]
    path = tmp_path / "core.png"
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path)
    return path


def test_resample_and_length():
    pts = [Point(x=0, y=0), Point(x=100, y=0)]
    assert abs(path_length(pts) - 100) < 1e-6
    s = resample_path(pts, step_px=1.0)
    assert s.total_length == 100
    assert len(s.xs) >= 100


def test_calibrate_scale():
    scale = calibrate_scale(Point(x=0, y=0), Point(x=100, y=0), 10.0, "mm")
    mpp = micrometers_per_pixel(scale)
    assert mpp is not None
    assert abs(mpp - 100.0) < 1e-6


def test_preprocess_presets():
    img = Image.fromarray(np.full((64, 64), 120, dtype=np.uint8))
    g = preprocess_gray(img, "sanded_core")
    assert g.shape == (64, 64)
    assert g.dtype == np.uint8


def test_classical_detect_synthetic(tmp_path: Path):
    path = _synthetic_core(tmp_path, n_rings=16)
    img = Image.open(path)
    pts = [Point(x=20, y=70), Point(x=680, y=70)]
    result = detect_rings_along_path(
        img, pts, preset="sanded_core", min_distance_px=12, prominence=0.05
    )
    assert len(result.rings) >= 8


def test_pipeline_export(tmp_path: Path):
    img_path = _synthetic_core(tmp_path, n_rings=12)
    project = run_detect(
        img_path,
        method="classical",
        preset="sanded_core",
        sample_type="core",
        outer_year=2020,
        sample_code="SYNTH01",
        min_distance_px=10,
        prominence=0.05,
    )
    assert project.paths and project.paths[0].rings
    out = tmp_path / "out"
    paths = export_all(project, out)
    assert Path(paths["rwl"]).is_file()
    assert Path(paths["pos"]).is_file()
    assert Path(paths["overlay"]).is_file()
    series = build_width_series(project)
    assert len(series.widths_px) >= 1


def test_rwl_roundtrip(tmp_path: Path):
    series = WidthSeries(
        years=list(range(2000, 2015)),
        widths_um=[100 + i * 3 for i in range(15)],
        widths_px=[10 + i for i in range(15)],
        flags=["ok"] * 15,
        sample_code="TEST01",
    )
    path = tmp_path / "t.rwl"
    write_rwl(series, path)
    parsed = read_rwl(path)
    assert "TEST01" in parsed
    assert 2000 in parsed["TEST01"]


def test_assign_years_and_missing():
    rings = [
        RingTick(distance_px=90, flag="ok"),
        RingTick(distance_px=70, flag="missing"),
        RingTick(distance_px=50, flag="ok"),
    ]
    labeled = assign_years(rings, 2020)
    years = [r.year for r in labeled]
    assert years == [2020, 2019, 2018]


def test_incline_correction():
    a = MeasurePath(
        id="a",
        points=[Point(x=0, y=0), Point(x=100, y=0)],
        rings=[RingTick(distance_px=80), RingTick(distance_px=40)],
    )
    b = MeasurePath(
        id="b",
        points=[Point(x=0, y=10), Point(x=100, y=10)],
        rings=[RingTick(distance_px=70), RingTick(distance_px=30)],
    )
    corr = incline_corrected_widths(a, b)
    assert len(corr) == 2
    assert abs(corr[0] - 40.0) < 1e-6


def test_polar_unwrap():
    img = np.zeros((200, 200), dtype=np.uint8)
    yy, xx = np.ogrid[:200, :200]
    r = np.sqrt((xx - 100) ** 2 + (yy - 100) ** 2)
    for rad in (20, 40, 60, 80):
        img[(r > rad - 1.5) & (r < rad + 1.5)] = 255
    polar = polar_unwrap(img, Point(x=100, y=100), max_radius=90, n_angles=180, n_radii=90)
    assert polar.shape == (180, 90)


def test_crossdate_self(tmp_path: Path):
    series = WidthSeries(
        years=list(range(1900, 1980)),
        widths_um=[80 + (i % 7) * 5 for i in range(80)],
        widths_px=[8.0] * 80,
        flags=["ok"] * 80,
        sample_code="S1",
    )
    path = tmp_path / "ref.rwl"
    write_rwl(series, path)
    hits = correlate_against_reference(series, path, min_overlap=30, max_lag=5)
    assert hits
    assert hits[0].lag == 0
    assert hits[0].correlation > 0.9
