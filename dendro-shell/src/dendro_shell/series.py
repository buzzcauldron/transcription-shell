"""Ring-width series, year labeling, incline correction."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dendro_shell.geometry import micrometers_per_pixel, path_length
from dendro_shell.project import MeasurePath, Project, RingTick


@dataclass
class WidthSeries:
    years: list[int]
    widths_um: list[float]
    widths_px: list[float]
    flags: list[str]
    sample_code: str


def assign_years(rings: list[RingTick], outer_year: int | None) -> list[RingTick]:
    """Label rings from outer (largest distance) inward. Rings should be sorted outer-first."""
    if outer_year is None:
        return rings
    # Ensure outer-first
    ordered = sorted(rings, key=lambda r: r.distance_px, reverse=True)
    year = int(outer_year)
    out: list[RingTick] = []
    for r in ordered:
        if r.flag == "missing":
            # missing ring occupies a year but has zero width later
            out.append(r.model_copy(update={"year": year}))
            year -= 1
            continue
        if r.flag == "false":
            out.append(r.model_copy(update={"year": None}))
            continue
        out.append(r.model_copy(update={"year": year}))
        year -= 1
    return out


def ring_widths_px(rings: list[RingTick], path_total: float) -> list[tuple[RingTick, float]]:
    """Widths between consecutive boundaries (outer → pith), plus bark-to-first if needed.

    Width for ring year Y is distance from outer edge of that ring to inner edge.
    Using sorted outer-first distances: width_i = d_i - d_{i+1}.
    """
    ordered = sorted(
        [r for r in rings if r.flag != "false"],
        key=lambda r: r.distance_px,
        reverse=True,
    )
    if not ordered:
        return []
    # Append pith end (distance 0) as final boundary
    dists = [r.distance_px for r in ordered] + [0.0]
    pairs: list[tuple[RingTick, float]] = []
    for i, r in enumerate(ordered):
        w = max(0.0, dists[i] - dists[i + 1])
        if r.flag == "missing":
            pairs.append((r, 0.0))
        else:
            pairs.append((r, w))
    return pairs


def incline_corrected_widths(
    path_a: MeasurePath,
    path_b: MeasurePath,
) -> list[float]:
    """MtreeRing-style: mean of two path widths with matching ring counts."""
    wa = [w for _, w in ring_widths_px(path_a.rings, path_length(path_a.points))]
    wb = [w for _, w in ring_widths_px(path_b.rings, path_length(path_b.points))]
    n = min(len(wa), len(wb))
    if n == 0:
        return []
    return [0.5 * (wa[i] + wb[i]) for i in range(n)]


def build_width_series(project: Project, path: MeasurePath | None = None) -> WidthSeries:
    path = path or project.primary_path()
    if path is None:
        return WidthSeries([], [], [], [], project.sample_code)

    rings = path.rings
    if project.outer_year is not None:
        rings = assign_years(rings, project.outer_year)
        path = path.model_copy(update={"rings": rings})

    pairs = ring_widths_px(rings, path_length(path.points))
    mpp = micrometers_per_pixel(project.scale)
    years: list[int] = []
    widths_px: list[float] = []
    widths_um: list[float] = []
    flags: list[str] = []
    for r, w in pairs:
        years.append(int(r.year) if r.year is not None else 0)
        widths_px.append(w)
        widths_um.append(w * mpp if mpp else w)
        flags.append(r.flag)

    # Incline correction if partner present
    if path.incline_partner_id:
        partner = next((p for p in project.paths if p.id == path.incline_partner_id), None)
        if partner is not None:
            corr = incline_corrected_widths(path, partner)
            if corr:
                widths_px = corr
                widths_um = [c * mpp if mpp else c for c in corr]
                years = years[: len(corr)]
                flags = flags[: len(corr)]

    return WidthSeries(
        years=years,
        widths_um=widths_um,
        widths_px=widths_px,
        flags=flags,
        sample_code=project.sample_code or "series",
    )


def skeleton_plot_values(widths_um: list[float]) -> list[float]:
    """Simple skeleton: mark years below mean as 1 else 0 (pointer years)."""
    if not widths_um:
        return []
    arr = np.asarray(widths_um, dtype=np.float64)
    # Ignore zeros (missing)
    valid = arr[arr > 0]
    if len(valid) == 0:
        return [0.0] * len(arr)
    thr = float(np.mean(valid))
    return [1.0 if (w > 0 and w < thr) else 0.0 for w in arr]
