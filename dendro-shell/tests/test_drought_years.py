"""Year labeling and drought/stress series diagnostics."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from dendro_shell.pipeline import export_all, run_detect
from dendro_shell.project import RingTick
from dendro_shell.series import (
    assign_years,
    drought_class_from_z,
    drought_stress_series,
    width_zscores,
)


def test_assign_years_outer_to_pith():
    rings = [
        RingTick(distance_px=100, flag="ok"),
        RingTick(distance_px=80, flag="ok"),
        RingTick(distance_px=60, flag="missing"),
        RingTick(distance_px=40, flag="ok"),
        RingTick(distance_px=90, flag="false"),
    ]
    labeled = assign_years(rings, 2020)
    by_d = {r.distance_px: r.year for r in labeled}
    assert by_d[100] == 2020
    assert by_d[80] == 2019
    assert by_d[60] == 2018  # missing still occupies a year
    assert by_d[40] == 2017
    assert by_d[90] is None  # false ring skipped


def test_drought_classes_from_widths():
    # clear dry / wet contrast
    widths = [100, 100, 100, 100, 40, 40, 160, 100, 100]
    z = width_zscores(widths)
    assert z[4] is not None and z[4] < -0.75
    assert drought_class_from_z(z[4]) in ("dry", "severe")
    assert drought_class_from_z(z[6]) == "wet"
    d = drought_stress_series(widths)
    assert d["n_stress"] >= 1
    assert len(d["class"]) == len(widths)
    assert "severe" in d["counts"]


def test_export_writes_drought_json(tmp_path: Path):
    w, h = 500, 100
    arr = np.full((h, w), 170, dtype=np.float32)
    xs = np.linspace(40, w - 40, 12)
    xx = np.arange(w)
    for x in xs:
        arr -= 40 * np.exp(-0.5 * ((xx - x) / 2.0) ** 2)[None, :]
    img = tmp_path / "c.png"
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(img)
    project = run_detect(
        img,
        method="classical",
        sample_type="core",
        outer_year=2020,
        sample_code="D1",
        min_distance_px=10,
        prominence=0.05,
        auto=False,
    )
    out = export_all(project, tmp_path / "out")
    assert Path(out["drought"]).is_file()
    text = Path(out["drought"]).read_text()
    assert "stress_frac" in text
    assert "2020" in text or '"year"' in text
