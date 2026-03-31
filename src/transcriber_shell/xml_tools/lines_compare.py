"""Compare two PageXML / lines files when a reference (e.g. Glyph Machina) is treated as ground truth."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


def _local_name(el: ET.Element) -> str:
    tag = el.tag
    if tag.startswith("{"):
        return tag.split("}", 1)[-1]
    return tag


def extract_textline_baselines(path: str | Path) -> list[list[tuple[float, float]]]:
    """Return ordered list of baseline polylines (page order). Skips TextLines without Baseline."""
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


def _centroid(poly: list[tuple[float, float]]) -> tuple[float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _euclid(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _sample_polyline(poly: list[tuple[float, float]], n: int) -> np.ndarray:
    """Sample ``n`` points along the polyline by arc length."""
    if not poly:
        return np.zeros((0, 2), dtype=np.float64)
    p = np.array(poly, dtype=np.float64)
    if len(p) == 1:
        return np.repeat(p, max(1, n), axis=0)
    seg = np.sqrt(np.sum(np.diff(p, axis=0) ** 2, axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total <= 0:
        return np.repeat(p[:1], n, axis=0)
    targets = np.linspace(0.0, total, n)
    out = np.zeros((n, 2), dtype=np.float64)
    j = 0
    for i, t in enumerate(targets):
        while j + 1 < len(cum) and cum[j + 1] < t:
            j += 1
        j = min(j, len(p) - 2)
        t0, t1 = cum[j], cum[j + 1]
        if t1 <= t0:
            out[i] = p[j]
        else:
            u = (t - t0) / (t1 - t0)
            out[i] = (1 - u) * p[j] + u * p[j + 1]
    return out


def chamfer_distance_px(
    ref: list[tuple[float, float]],
    hyp: list[tuple[float, float]],
    *,
    n_samples: int = 32,
) -> float:
    """Symmetric Chamfer-like distance (mean of min distances both ways)."""
    r = _sample_polyline(ref, n_samples)
    h = _sample_polyline(hyp, n_samples)
    if len(r) == 0 or len(h) == 0:
        return float("nan")
    # (nr, nh) distances
    d_rh = np.linalg.norm(r[:, None, :] - h[None, :, :], axis=2)
    d_hr = d_rh.T
    return 0.5 * float(d_rh.min(axis=1).mean() + d_hr.min(axis=1).mean())


def match_baselines(
    ref_polys: list[list[tuple[float, float]]],
    hyp_polys: list[list[tuple[float, float]]],
    *,
    centroid_match_px: float,
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """Greedy match by centroid distance (hypothesis lines assigned at most once)."""
    if not ref_polys:
        return [], [], list(range(len(hyp_polys)))
    if not hyp_polys:
        return [], list(range(len(ref_polys))), []

    ref_c = [_centroid(p) for p in ref_polys]
    hyp_c = [_centroid(p) for p in hyp_polys]
    ref_order = sorted(range(len(ref_polys)), key=lambda i: (ref_c[i][1], ref_c[i][0]))
    used_hyp: set[int] = set()
    pairs: list[tuple[int, int, float]] = []

    for ri in ref_order:
        best_j: int | None = None
        best_d = centroid_match_px
        for hj in range(len(hyp_polys)):
            if hj in used_hyp:
                continue
            d = _euclid(ref_c[ri], hyp_c[hj])
            if d < best_d:
                best_d = d
                best_j = hj
        if best_j is not None:
            pairs.append((ri, best_j, best_d))
            used_hyp.add(best_j)

    matched_ref = {p[0] for p in pairs}
    matched_hyp = {p[1] for p in pairs}
    unmatched_ref = [i for i in range(len(ref_polys)) if i not in matched_ref]
    unmatched_hyp = [j for j in range(len(hyp_polys)) if j not in matched_hyp]
    return pairs, unmatched_ref, unmatched_hyp


@dataclass
class LineationComparison:
    """Reference = ground truth (e.g. Glyph Machina); hypothesis = local model output."""

    reference_lines: int
    hypothesis_lines: int
    matched_pairs: int
    unmatched_reference_indices: list[int]
    unmatched_hypothesis_indices: list[int]
    mean_chamfer_px: float | None
    chamfer_per_pair_px: list[float]
    recall_vs_reference: float
    precision_vs_reference: float
    centroid_match_threshold_px: float

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def compare_lines_xml(
    reference_path: str | Path,
    hypothesis_path: str | Path,
    *,
    centroid_match_px: float = 120.0,
    chamfer_samples: int = 32,
) -> LineationComparison:
    """Compare hypothesis lines XML to reference (assumed perfect)."""
    ref_path = Path(reference_path)
    hyp_path = Path(hypothesis_path)
    ref_polys = extract_textline_baselines(ref_path)
    hyp_polys = extract_textline_baselines(hyp_path)

    pairs, uref, uhyp = match_baselines(
        ref_polys, hyp_polys, centroid_match_px=centroid_match_px
    )
    chamfers: list[float] = []
    for ri, hj, _ in pairs:
        c = chamfer_distance_px(
            ref_polys[ri], hyp_polys[hj], n_samples=chamfer_samples
        )
        if not math.isnan(c):
            chamfers.append(c)

    mean_ch: float | None
    if chamfers:
        mean_ch = float(sum(chamfers) / len(chamfers))
    else:
        mean_ch = None

    n_ref = len(ref_polys)
    n_hyp = len(hyp_polys)
    matched = len(pairs)
    recall = matched / n_ref if n_ref else 1.0
    precision = matched / n_hyp if n_hyp else 1.0

    return LineationComparison(
        reference_lines=n_ref,
        hypothesis_lines=n_hyp,
        matched_pairs=matched,
        unmatched_reference_indices=uref,
        unmatched_hypothesis_indices=uhyp,
        mean_chamfer_px=mean_ch,
        chamfer_per_pair_px=chamfers,
        recall_vs_reference=recall,
        precision_vs_reference=precision,
        centroid_match_threshold_px=centroid_match_px,
    )


def format_comparison_report(result: LineationComparison, *, as_json: bool) -> str:
    """Human or JSON report string."""
    if as_json:
        return json.dumps(result.to_json_dict(), indent=2)
    lines = [
        f"reference_lines={result.reference_lines} (ground truth)",
        f"hypothesis_lines={result.hypothesis_lines} (local)",
        f"matched_pairs={result.matched_pairs}",
        f"recall_vs_reference={result.recall_vs_reference:.4f}  (matched / reference)",
        f"precision_vs_reference={result.precision_vs_reference:.4f}  (matched / hypothesis)",
    ]
    if result.mean_chamfer_px is not None:
        lines.append(f"mean_chamfer_px={result.mean_chamfer_px:.2f}  (on matched baselines)")
    else:
        lines.append("mean_chamfer_px=n/a")
    if result.unmatched_reference_indices:
        lines.append(
            f"missed_reference_line_indices={result.unmatched_reference_indices}"
        )
    if result.unmatched_hypothesis_indices:
        lines.append(
            f"extra_hypothesis_line_indices={result.unmatched_hypothesis_indices}"
        )
    return "\n".join(lines) + "\n"
