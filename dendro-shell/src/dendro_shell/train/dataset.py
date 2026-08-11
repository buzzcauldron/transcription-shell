"""Build training crops/masks from the DendroLibrary / project JSONs."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from dendro_shell.geometry import point_at_distance, resample_path
from dendro_shell.paths import default_library_dir
from dendro_shell.project import Project


def rasterize_boundary_mask(
    image_shape: tuple[int, int],
    project: Project,
    ribbon_radius: int = 2,
) -> np.ndarray:
    """HxW uint8 mask with ring-boundary ribbons along paths."""
    h, w = image_shape
    mask = np.zeros((h, w), dtype=np.uint8)
    for mp in project.paths:
        if len(mp.points) < 2:
            continue
        for r in mp.rings:
            if r.flag in ("false",):
                continue
            pt = point_at_distance(mp.points, r.distance_px)
            cv2.circle(
                mask,
                (int(round(pt.x)), int(round(pt.y))),
                ribbon_radius,
                255,
                -1,
                lineType=cv2.LINE_AA,
            )
        # Also draw short normal segments for visibility on sparse ticks
        sample = resample_path(mp.points, step_px=2.0)
        for r in mp.rings:
            if r.flag == "false":
                continue
            # nearest sample index
            idx = int(np.argmin(np.abs(sample.distances - r.distance_px)))
            if idx <= 0 or idx >= len(sample.xs) - 1:
                continue
            tx = sample.xs[idx + 1] - sample.xs[idx - 1]
            ty = sample.ys[idx + 1] - sample.ys[idx - 1]
            norm = math.hypot(tx, ty) + 1e-8
            nx, ny = -ty / norm, tx / norm
            x0 = int(round(sample.xs[idx] - nx * 8))
            y0 = int(round(sample.ys[idx] - ny * 8))
            x1 = int(round(sample.xs[idx] + nx * 8))
            y1 = int(round(sample.ys[idx] + ny * 8))
            cv2.line(mask, (x0, y0), (x1, y1), 255, ribbon_radius, cv2.LINE_AA)
    if project.paint_mask:
        paint_path = Path(project.paint_mask)
        if not paint_path.is_file() and project.image_path:
            paint_path = Path(project.image_path).parent / project.paint_mask
        if paint_path.is_file():
            paint = np.asarray(Image.open(paint_path).convert("L"))
            if paint.shape[:2] == mask.shape:
                mask = np.maximum(mask, (paint > 127).astype(np.uint8) * 255)
    return mask


def add_project_to_library(
    project: Project,
    library_dir: Path | str | None = None,
    *,
    name: str | None = None,
) -> Path:
    """Copy image + project JSON + raster mask into the training library."""
    library_dir = Path(library_dir or default_library_dir())
    library_dir.mkdir(parents=True, exist_ok=True)
    stem = name or project.sample_code or Path(project.image_path).stem
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
    dest = library_dir / stem
    dest.mkdir(parents=True, exist_ok=True)

    img_src = Path(project.image_path)
    if not img_src.is_file():
        raise FileNotFoundError(f"Image not found: {img_src}")
    img_dest = dest / img_src.name
    if img_dest.resolve() != img_src.resolve():
        shutil.copy2(img_src, img_dest)

    image = Image.open(img_dest)
    mask = rasterize_boundary_mask((image.height, image.width), project)
    mask_path = dest / "boundary_mask.png"
    Image.fromarray(mask).save(mask_path)

    proj = project.model_copy(
        update={"image_path": str(img_dest), "paint_mask": str(mask_path)}
    )
    proj.save(dest / "project.json")
    meta = {
        "sample_code": proj.sample_code,
        "species": proj.species,
        "tags": proj.tags,
        "n_rings": sum(len(p.rings) for p in proj.paths),
    }
    (dest / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return dest


def list_library_entries(library_dir: Path | str | None = None) -> list[dict]:
    library_dir = Path(library_dir or default_library_dir())
    if not library_dir.is_dir():
        return []
    out = []
    for child in sorted(library_dir.iterdir()):
        pj = child / "project.json"
        if not pj.is_file():
            continue
        meta_path = child / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
        out.append({"id": child.name, "path": str(child), **meta})
    return out


def iter_training_samples(
    library_dir: Path | str | None = None,
    *,
    species: str | None = None,
    tag: str | None = None,
):
    library_dir = Path(library_dir or default_library_dir())
    for entry in list_library_entries(library_dir):
        if species and entry.get("species") != species:
            continue
        if tag and tag not in (entry.get("tags") or []):
            continue
        root = Path(entry["path"])
        proj = Project.load(root / "project.json")
        img = Image.open(proj.image_path).convert("L")
        mask_path = root / "boundary_mask.png"
        if mask_path.is_file():
            mask = np.asarray(Image.open(mask_path).convert("L"))
        else:
            mask = rasterize_boundary_mask((img.height, img.width), proj)
        yield proj, np.asarray(img), mask


class RingCropDataset:
    """Torch Dataset of random square crops."""

    def __init__(
        self,
        samples: list[tuple[np.ndarray, np.ndarray]],
        imgsz: int = 512,
        augment: bool = True,
    ):
        self.samples = samples
        self.imgsz = imgsz
        self.augment = augment

    def __len__(self) -> int:
        return max(len(self.samples), 1) * 8

    def __getitem__(self, idx: int):
        import torch

        img, mask = self.samples[idx % len(self.samples)]
        h, w = img.shape[:2]
        side = min(h, w, self.imgsz)
        if h >= side and w >= side:
            y0 = int(np.random.randint(0, h - side + 1))
            x0 = int(np.random.randint(0, w - side + 1))
            img_c = img[y0 : y0 + side, x0 : x0 + side]
            mask_c = mask[y0 : y0 + side, x0 : x0 + side]
        else:
            img_c = img
            mask_c = mask
        img_r = np.asarray(
            Image.fromarray(img_c).resize((self.imgsz, self.imgsz), Image.BILINEAR)
        )
        mask_r = np.asarray(
            Image.fromarray(mask_c).resize((self.imgsz, self.imgsz), Image.NEAREST)
        )
        if self.augment:
            if np.random.rand() < 0.5:
                img_r = np.fliplr(img_r).copy()
                mask_r = np.fliplr(mask_r).copy()
            if np.random.rand() < 0.5:
                img_r = np.flipud(img_r).copy()
                mask_r = np.flipud(mask_r).copy()
            # contrast / brightness
            alpha = 0.7 + 0.6 * np.random.rand()
            beta = np.random.randint(-20, 21)
            img_r = np.clip(img_r.astype(np.float32) * alpha + beta, 0, 255).astype(np.uint8)
            if np.random.rand() < 0.3:
                k = 3
                img_r = cv2.GaussianBlur(img_r, (k, k), 0)

        x = torch.from_numpy(img_r.astype(np.float32) / 255.0)[None]
        y = torch.from_numpy((mask_r > 127).astype(np.float32))[None]
        return x, y


def load_sample_arrays(
    library_dir: Path | str | None = None,
    species: str | None = None,
    tag: str | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    return [(img, mask) for _, img, mask in iter_training_samples(library_dir, species=species, tag=tag)]
