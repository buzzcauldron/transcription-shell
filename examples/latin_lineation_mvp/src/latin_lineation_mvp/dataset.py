"""Paired JPG + PageXML from latin_documents ``data/`` → train/val splits and mask tensors."""

from __future__ import annotations

import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def _local_name(el: ET.Element) -> str:
    tag = el.tag
    if tag.startswith("{"):
        return tag.split("}", 1)[-1]
    return tag


def extract_textline_baselines_from_xml(path: str | Path) -> list[list[tuple[float, float]]]:
    """Page-order baseline polylines (same convention as transcriber_shell.xml_tools.lines_compare)."""
    tree = ET.parse(path)
    root = tree.getroot()
    polys: list[list[tuple[float, float]]] = []
    for el in root.iter():
        if _local_name(el) != "TextLine":
            continue
        bl_el = None
        for child in el:
            if _local_name(child) == "Baseline":
                bl_el = child
                break
        if bl_el is None:
            continue
        raw = bl_el.get("points")
        if not raw or not str(raw).strip():
            continue
        pts: list[tuple[float, float]] = []
        for pair in str(raw).split():
            if "," not in pair:
                continue
            a, b = pair.split(",", 1)
            try:
                pts.append((float(a), float(b)))
            except ValueError:
                continue
        if len(pts) >= 1:
            polys.append(pts)
    return polys


def filter_pairs_with_lines(
    pairs: list[tuple[Path, Path]],
) -> list[tuple[Path, Path]]:
    """Keep only pages that have at least one TextLine baseline."""
    out: list[tuple[Path, Path]] = []
    for img_p, xml_p in pairs:
        if len(extract_textline_baselines_from_xml(xml_p)) >= 1:
            out.append((img_p, xml_p))
    return out


def find_page_pairs(data_dir: Path) -> list[tuple[Path, Path]]:
    """Return sorted list of (jpg_path, xml_path) for stems that have both."""
    data_dir = data_dir.expanduser().resolve()
    if not data_dir.is_dir():
        raise FileNotFoundError(f"data dir not found: {data_dir}")
    pairs: list[tuple[Path, Path]] = []
    for xml_path in sorted(data_dir.glob("*.xml")):
        stem = xml_path.stem
        for ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
            img = data_dir / f"{stem}{ext}"
            if img.is_file():
                pairs.append((img, xml_path))
                break
    return pairs


def split_train_val(
    pairs: list[tuple[Path, Path]],
    *,
    val_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[list[tuple[Path, Path]], list[tuple[Path, Path]]]:
    """Split by page stem; ``val_ratio`` in (0,1)."""
    if not pairs:
        return [], []
    rng = random.Random(seed)
    items = list(pairs)
    rng.shuffle(items)
    n_val = max(1, int(len(items) * val_ratio)) if len(items) > 1 else 0
    if len(items) == 1:
        return items, []
    val = items[:n_val]
    train = items[n_val:]
    return train, val


def rasterize_baselines(
    polys: list[list[tuple[float, float]]],
    height: int,
    width: int,
    *,
    line_width: int = 4,
) -> np.ndarray:
    """One binary mask per line, shape ``(L, height, width)`` float32 in ``[0,1]``."""
    if height < 1 or width < 1:
        raise ValueError("invalid raster size")
    if not polys:
        return np.zeros((0, height, width), dtype=np.float32)
    out: list[np.ndarray] = []
    for poly in polys:
        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        pts = [(int(round(p[0])), int(round(p[1]))) for p in poly]
        if len(pts) == 1:
            x, y = pts[0]
            r = max(1, line_width // 2)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=255)
        else:
            draw.line(pts, fill=255, width=max(1, line_width))
        arr = np.asarray(mask, dtype=np.float32) / 255.0
        out.append(arr)
    return np.stack(out, axis=0)


def load_image_rgb(path: Path) -> np.ndarray:
    """``(H, W, 3)`` float32 in ``[0,1]``."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        arr = np.asarray(im, dtype=np.float32) / 255.0
    return arr


@dataclass
class PageSample:
    """Image and masks at model resolution (``mask_h``, ``mask_w``)."""

    image_path: Path
    image: np.ndarray  # (3, H, W)
    masks: np.ndarray  # (max_lines, H, W)
    valid: np.ndarray  # (max_lines,) 1.0 for real lines, 0.0 for padding


def max_lines_in_pairs(pairs: list[tuple[Path, Path]]) -> int:
    m = 1
    for _, xml in pairs:
        n = len(extract_textline_baselines_from_xml(xml))
        m = max(m, n)
    return m


def build_page_sample(
    img_path: Path,
    xml_path: Path,
    *,
    mask_h: int,
    mask_w: int,
    max_lines: int,
    line_width: int,
) -> PageSample:
    """Resize image to ``(mask_h, mask_w)``; rasterize baselines in the same pixel space."""
    rgb = load_image_rgb(img_path)  # H, W, 3
    ih, iw = rgb.shape[0], rgb.shape[1]
    polys = extract_textline_baselines_from_xml(xml_path)
    # Scale baseline coords to mask grid
    sx = mask_w / max(iw, 1)
    sy = mask_h / max(ih, 1)
    scaled: list[list[tuple[float, float]]] = []
    for poly in polys:
        scaled.append([(p[0] * sx, p[1] * sy) for p in poly])
    raw = rasterize_baselines(scaled, mask_h, mask_w, line_width=line_width)
    L = raw.shape[0]
    if L > max_lines:
        raise ValueError(f"page has {L} lines > max_lines={max_lines}")
    padded = np.zeros((max_lines, mask_h, mask_w), dtype=np.float32)
    valid = np.zeros((max_lines,), dtype=np.float32)
    if L > 0:
        padded[:L] = raw
        valid[:L] = 1.0
    # image (3, H, W)
    img_rs = np.array(
        Image.fromarray((rgb * 255).astype(np.uint8)).resize(
            (mask_w, mask_h), Image.Resampling.BILINEAR
        ),
        dtype=np.float32,
    ) / 255.0
    img_chw = np.transpose(img_rs, (2, 0, 1))
    return PageSample(
        image_path=img_path,
        image=img_chw,
        masks=padded,
        valid=valid,
    )
