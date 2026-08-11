"""Training library + optional short U-Net train (skipped if no torch)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dendro_shell.pipeline import run_detect
from dendro_shell.train.dataset import add_project_to_library, list_library_entries, rasterize_boundary_mask
from dendro_shell.train.registry import get_active_checkpoint, list_models, load_manifest


def _core(tmp_path: Path) -> Path:
    w, h = 400, 100
    img = np.full((h, w), 165, dtype=np.float32)
    xs = np.linspace(30, w - 30, 10)
    xx = np.arange(w)
    for x in xs:
        img -= 45 * np.exp(-0.5 * ((xx - x) / 2.0) ** 2)[None, :]
    p = tmp_path / "c.png"
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(p)
    return p


def test_library_add_and_mask(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DENDRO_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.setenv("DENDRO_CACHE", str(tmp_path / "cache"))
    img = _core(tmp_path)
    project = run_detect(img, sample_code="LIB1", min_distance_px=8, prominence=0.05)
    dest = add_project_to_library(project, tmp_path / "lib")
    assert (dest / "project.json").is_file()
    assert (dest / "boundary_mask.png").is_file()
    entries = list_library_entries(tmp_path / "lib")
    assert len(entries) == 1
    mask = np.asarray(Image.open(dest / "boundary_mask.png"))
    assert mask.max() > 0


def test_rasterize_empty_path():
    from dendro_shell.project import Project

    p = Project(image_path="x.png", paths=[])
    mask = rasterize_boundary_mask((32, 32), p)
    assert mask.shape == (32, 32)
    assert mask.sum() == 0


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("torch") is None,
    reason="torch not installed",
)
def test_short_train(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DENDRO_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.setenv("DENDRO_CACHE", str(tmp_path / "cache"))
    lib = tmp_path / "lib"
    for i in range(3):
        sample_dir = tmp_path / f"s{i}"
        sample_dir.mkdir(exist_ok=True)
        img = _core(sample_dir)
        project = run_detect(img, sample_code=f"T{i}", min_distance_px=8, prominence=0.05)
        add_project_to_library(project, lib, name=f"T{i}")

    from dendro_shell.train.job import TrainConfig, run_training

    st = run_training(
        TrainConfig(
            library_dir=str(lib),
            name="test_unet",
            epochs=2,
            imgsz=128,
            batch_size=1,
            device="cpu",
            fine_tune=False,
            activate=True,
            overwrite=True,
            min_samples_warn=1,
        ),
        background=False,
    )
    assert st.state == "finished"
    assert get_active_checkpoint() is not None
    assert any(m["name"] == "test_unet" for m in list_models())
    assert load_manifest()["active"] == "test_unet"
