"""Letter-height fingerprint for paleographic comparison.

Computes a per-document distribution of ink heights from PAGE XML line polygons
and the source image, without depending on HTR. Each connected component within
a line crop is treated as one "glyph" and measured in pixels; per-line median
normalisation removes scale and line-height variance. The result is a stable
signature that distinguishes script types (Gothic vs Caroline) and, given
enough data, individual hands.

The fingerprint is HTR-independent so it can run **before** transcription and
drive doc-type selection — see ``compare`` and the ``fingerprint-match`` CLI.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import label as _cc_label, find_objects as _cc_bbox


_QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)
_QUANTILE_KEYS = ("p05", "p25", "p50", "p75", "p95")
_HIST_EDGES = tuple(round(x, 4) for x in np.linspace(0.0, 3.0, 21).tolist())  # 20 bins, 0–3×line-median


@dataclass
class Fingerprint:
    doc_id: str
    n_lines: int
    n_components: int
    n_components_kept: int
    height_mean: float
    height_std: float
    height_quantiles: dict[str, float]
    histogram_edges: list[float]
    histogram_density: list[float]
    doc_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Fingerprint":
        return cls(
            doc_id=d["doc_id"],
            n_lines=int(d["n_lines"]),
            n_components=int(d["n_components"]),
            n_components_kept=int(d["n_components_kept"]),
            height_mean=float(d["height_mean"]),
            height_std=float(d["height_std"]),
            height_quantiles={k: float(v) for k, v in d["height_quantiles"].items()},
            histogram_edges=[float(v) for v in d["histogram_edges"]],
            histogram_density=[float(v) for v in d["histogram_density"]],
            doc_type=d.get("doc_type"),
        )


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = q * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)


def _parse_points(points: str) -> list[tuple[int, int]]:
    """Parse a PAGE XML points string in either 'x,y x,y' or 'x y x y' format."""
    toks = points.split()
    if not toks:
        return []
    if "," in toks[0]:
        pts: list[tuple[int, int]] = []
        for tok in toks:
            if "," not in tok:
                continue
            xs, _, ys = tok.partition(",")
            try:
                pts.append((int(round(float(xs))), int(round(float(ys)))))
            except ValueError:
                continue
        return pts
    # Flat list: alternating x y x y
    nums: list[float] = []
    for tok in toks:
        try:
            nums.append(float(tok))
        except ValueError:
            return []
    return [(int(round(nums[i])), int(round(nums[i + 1]))) for i in range(0, len(nums) - 1, 2)]


def _parse_line_polygons(xml_path: Path) -> list[list[tuple[int, int]]]:
    """Return list of line polygons in image coords. Skips lines without Coords."""
    root = ET.parse(str(xml_path)).getroot()
    polygons: list[list[tuple[int, int]]] = []
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag != "TextLine":
            continue
        coords_el = None
        for child in el:
            ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if ctag == "Coords":
                coords_el = child
                break
        if coords_el is None or not coords_el.get("points"):
            continue
        pts = _parse_points(coords_el.get("points", ""))
        if len(pts) >= 3:
            polygons.append(pts)
    return polygons


def _otsu_threshold(arr: np.ndarray) -> int:
    """Simple Otsu on a uint8 array. Returns the threshold value."""
    hist = np.bincount(arr.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total <= 0:
        return 128
    sum_total = float((np.arange(256) * hist).sum())
    sum_b = 0.0
    w_b = 0.0
    var_max = 0.0
    threshold = 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        var_between = w_b * w_f * (m_b - m_f) ** 2
        if var_between > var_max:
            var_max = var_between
            threshold = t
    return threshold


def _polygon_mask(shape: tuple[int, int], polygon: list[tuple[int, int]]) -> np.ndarray:
    """Rasterise a polygon to a boolean mask using PIL (fast C path)."""
    H, W = shape[0], shape[1]
    if len(polygon) < 3:
        return np.zeros((H, W), dtype=bool)
    mask_img = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask_img).polygon(polygon, fill=1)
    return np.asarray(mask_img, dtype=bool)


def _line_component_heights(
    image_arr: np.ndarray,
    polygon: list[tuple[int, int]],
    *,
    min_height_px: int,
    max_height_px: int,
) -> list[int]:
    """Crop, mask, binarise, label connected components, return component heights in px."""
    if not polygon:
        return []
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    H, W = image_arr.shape[:2]
    x0, x1 = max(0, min(xs)), min(W, max(xs) + 1)
    y0, y1 = max(0, min(ys)), min(H, max(ys) + 1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return []

    crop = image_arr[y0:y1, x0:x1]
    if crop.ndim == 3:
        # Rec. 601 grayscale
        crop = (0.299 * crop[..., 0] + 0.587 * crop[..., 1] + 0.114 * crop[..., 2]).astype(np.uint8)
    else:
        crop = crop.astype(np.uint8)

    poly_rel = [(p[0] - x0, p[1] - y0) for p in polygon]
    mask = _polygon_mask(crop.shape, poly_rel)

    inside = crop[mask]
    if inside.size < 32:
        return []
    thresh = _otsu_threshold(inside)
    binary = (crop < thresh) & mask

    crop_h = y1 - y0
    min_h = max(2, min_height_px)
    max_h = min(crop_h, max_height_px)

    labels, n = _cc_label(binary)
    if n == 0:
        return []
    heights: list[int] = []
    for sl in _cc_bbox(labels):
        if sl is None:
            continue
        h = sl[0].stop - sl[0].start
        if min_h <= h <= max_h:
            heights.append(int(h))
    return heights


def extract_doc_heights(
    image_path: Path,
    lines_xml_path: Path,
    *,
    min_height_px: int = 4,
    max_height_px: int = 400,
) -> tuple[list[float], int, int]:
    """Return (normalized_heights, n_lines, n_components_seen).

    Each line's connected components are measured in pixels; heights are
    normalised by that line's median. Output values are the per-component
    normalised heights pooled across all lines.
    """
    image_path = Path(image_path)
    lines_xml_path = Path(lines_xml_path)
    if not image_path.is_file():
        raise FileNotFoundError(f"image not found: {image_path}")
    if not lines_xml_path.is_file():
        raise FileNotFoundError(f"lines XML not found: {lines_xml_path}")

    polygons = _parse_line_polygons(lines_xml_path)
    if not polygons:
        return [], 0, 0

    im = Image.open(image_path)
    im.load()
    arr = np.asarray(im)

    normalized: list[float] = []
    n_seen = 0
    for polygon in polygons:
        heights = _line_component_heights(
            arr, polygon,
            min_height_px=min_height_px,
            max_height_px=max_height_px,
        )
        n_seen += len(heights)
        if len(heights) < 3:
            continue
        median = float(np.median(heights))
        if median <= 0:
            continue
        for h in heights:
            normalized.append(h / median)

    return normalized, len(polygons), n_seen


def build_fingerprint(
    heights: list[float],
    doc_id: str,
    *,
    n_lines: int,
    n_components: int,
    doc_type: str | None = None,
) -> Fingerprint:
    """Aggregate normalised heights into a fingerprint."""
    kept = len(heights)
    if heights:
        arr = np.asarray(heights, dtype=np.float64)
        mean = float(arr.mean())
        std = float(arr.std())
        sorted_h = sorted(heights)
        quantiles = {k: round(_quantile(sorted_h, q), 4) for k, q in zip(_QUANTILE_KEYS, _QUANTILES)}
        counts, _ = np.histogram(arr, bins=np.asarray(_HIST_EDGES))
        density = counts.astype(np.float64)
        s = density.sum()
        if s > 0:
            density = density / s
        density_list = [round(float(v), 6) for v in density.tolist()]
    else:
        mean = 0.0
        std = 0.0
        quantiles = {k: 0.0 for k in _QUANTILE_KEYS}
        density_list = [0.0] * (len(_HIST_EDGES) - 1)

    return Fingerprint(
        doc_id=doc_id,
        n_lines=n_lines,
        n_components=n_components,
        n_components_kept=kept,
        height_mean=round(mean, 4),
        height_std=round(std, 4),
        height_quantiles=quantiles,
        histogram_edges=list(_HIST_EDGES),
        histogram_density=density_list,
        doc_type=doc_type,
    )


def _script_vector(fp: Fingerprint) -> np.ndarray:
    return np.asarray([
        fp.height_mean,
        fp.height_std,
        *(fp.height_quantiles[k] for k in _QUANTILE_KEYS),
    ], dtype=np.float64)


def _emd_1d(p: Sequence[float], q: Sequence[float]) -> float:
    """Earth-mover distance on two 1-D probability vectors of equal length."""
    p_arr = np.asarray(p, dtype=np.float64)
    q_arr = np.asarray(q, dtype=np.float64)
    if p_arr.shape != q_arr.shape:
        return float("nan")
    cdf_p = np.cumsum(p_arr)
    cdf_q = np.cumsum(q_arr)
    return float(np.abs(cdf_p - cdf_q).sum())


def compare(a: Fingerprint, b: Fingerprint) -> dict[str, Any]:
    """Compare two fingerprints. Returns distance metrics and a 0–1 similarity."""
    if a.n_components_kept == 0 or b.n_components_kept == 0:
        return {
            "a": a.doc_id, "b": b.doc_id,
            "script_distance": None, "shape_distance": None,
            "combined_distance": None, "similarity": 0.0,
            "warning": "one or both fingerprints have no components",
        }

    va = _script_vector(a)
    vb = _script_vector(b)
    script_dist = float(np.linalg.norm(va - vb))
    shape_dist = _emd_1d(a.histogram_density, b.histogram_density)

    combined = 0.3 * script_dist + 0.7 * shape_dist
    # Map distance → similarity in [0,1]. Empirically combined < ~1.5 is "same script".
    similarity = float(math.exp(-combined))

    return {
        "a": a.doc_id,
        "b": b.doc_id,
        "script_distance": round(script_dist, 4),
        "shape_distance": round(shape_dist, 4),
        "combined_distance": round(combined, 4),
        "similarity": round(similarity, 4),
    }


def compare_batch(fps: list[Fingerprint]) -> list[list[float]]:
    """Pairwise combined-distance matrix; diagonal is 0. None distances become inf."""
    n = len(fps)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = compare(fps[i], fps[j])["combined_distance"]
            v = float("inf") if d is None else float(d)
            matrix[i][j] = v
            matrix[j][i] = v
    return matrix


def match_against_library(
    target: Fingerprint,
    library: list[Fingerprint],
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Rank library entries by similarity to target. Returns top_k."""
    scored = [compare(target, fp) | {"doc_type": fp.doc_type} for fp in library]
    scored.sort(key=lambda r: (r["combined_distance"] is None, r["combined_distance"] or 0.0))
    return scored[:top_k]


def suggest_doc_type(
    target: Fingerprint,
    library: list[Fingerprint],
    *,
    top_k: int = 3,
    min_similarity: float = 0.5,
) -> dict[str, Any]:
    """Suggest a doc-type from the library when the top-K matches agree."""
    matches = match_against_library(target, library, top_k=top_k)
    typed = [m for m in matches if m.get("doc_type") and m["similarity"] >= min_similarity]
    if not typed:
        return {"suggested_doc_type": None, "matches": matches, "reason": "no library entries above similarity threshold"}

    votes: dict[str, float] = {}
    for m in typed:
        votes[m["doc_type"]] = votes.get(m["doc_type"], 0.0) + m["similarity"]
    best = max(votes.items(), key=lambda kv: kv[1])
    return {
        "suggested_doc_type": best[0],
        "vote_score": round(best[1], 4),
        "matches": matches,
    }


def load_fingerprint_json(path: Path) -> list[Fingerprint]:
    """Load one or many fingerprints from a JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [Fingerprint.from_dict(d) for d in data]
    return [Fingerprint.from_dict(data)]
