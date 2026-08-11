"""Detection stack registry and auto defaults."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dendro_shell.detect.classical import infer_sample_type
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


def test_infer_round_blob_is_disc_even_in_wide_frame(tmp_path: Path):
    """Rectangular photo of a round section should still classify as disc."""
    w, h = 640, 420
    arr = np.full((h, w), 230, dtype=np.uint8)
    yy, xx = np.ogrid[:h, :w]
    cx, cy = w // 2, h // 2
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    arr[r < 160] = 120
    for rad in np.linspace(30, 150, 10):
        arr[(r > rad - 1.2) & (r < rad + 1.2)] = 40
    path = tmp_path / "framed_disc.png"
    Image.fromarray(arr).save(path)
    assert infer_sample_type(Image.open(path)) == "disc"


def test_infer_elongated_core(tmp_path: Path):
    w, h = 700, 140
    arr = np.full((h, w), 170, dtype=np.uint8)
    for x in np.linspace(40, w - 40, 14):
        arr[:, int(x) - 1 : int(x) + 2] = 50
    path = tmp_path / "core.png"
    Image.fromarray(arr).save(path)
    assert infer_sample_type(Image.open(path)) == "core"


def test_unet_without_checkpoint_raises():
    from pathlib import Path as P

    # Use tiny blank; run_detect should raise before inventing rings
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        img = P(td) / "x.png"
        Image.fromarray(np.full((80, 200), 160, dtype=np.uint8)).save(img)
        with pytest.raises(FileNotFoundError, match="U-Net checkpoint"):
            run_detect(img, method="unet", sample_type="core", auto=False)
