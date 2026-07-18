"""Detection stack registry and auto defaults."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from dendro_shell.detect.methods import (
    METHOD_IDS,
    default_method_for,
    list_detect_methods,
    method_payload,
    resolve_method,
)
from dendro_shell.pipeline import run_detect


def test_stack_includes_boolean():
    ids = [m["id"] for m in list_detect_methods()]
    assert ids == ["classical", "boolean", "unet"]
    assert "boolean" in METHOD_IDS
    payload = method_payload()
    assert payload["methods"] == list(METHOD_IDS)
    assert payload["defaults"]["disc"] == "boolean"
    assert payload["defaults"]["core"] == "classical"


def test_resolve_auto_by_type():
    assert default_method_for("disc") == "boolean"
    assert default_method_for("core") == "classical"
    assert resolve_method("auto", sample_type="disc") == "boolean"
    assert resolve_method("auto", sample_type="core") == "classical"
    assert resolve_method("boolean", sample_type="core") == "boolean"
    assert resolve_method("unknown", sample_type="disc") == "boolean"


def test_pipeline_auto_disc_uses_boolean(tmp_path: Path):
    """Near-square image → disc → auto method resolves to boolean."""
    size = 320
    arr = np.full((size, size), 200, dtype=np.uint8)
    yy, xx = np.ogrid[:size, :size]
    cx = cy = size // 2
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    for rad in np.linspace(25, 140, 12):
        band = (r > rad - 1.0) & (r < rad + 1.0)
        arr[band] = 50
    path = tmp_path / "disc.png"
    Image.fromarray(arr).save(path)
    project = run_detect(
        path,
        method="auto",
        sample_type="disc",
        preset="sanded_core",
        outer_year=2020,
        sample_code="AUTO",
        auto=False,
    )
    assert project.detect_method == "boolean"
    assert len(project.paths[0].rings) >= 4
