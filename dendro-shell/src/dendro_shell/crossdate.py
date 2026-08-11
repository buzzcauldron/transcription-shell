"""Light crossdating helper against a reference .rwl."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from dendro_shell.export.rwl import read_rwl
from dendro_shell.series import WidthSeries


@dataclass
class CrossdateHit:
    lag: int
    correlation: float
    overlap: int
    reference_id: str


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return 0.0
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.sqrt(np.sum(a * a) * np.sum(b * b)))
    if denom <= 1e-12:
        return 0.0
    return float(np.sum(a * b) / denom)


def series_to_year_map(series: WidthSeries) -> dict[int, float]:
    return {int(y): float(w) for y, w in zip(series.years, series.widths_um) if y}


def correlate_against_reference(
    sample: WidthSeries | dict[int, float],
    reference: dict[int, float] | Path | str,
    *,
    reference_id: str | None = None,
    min_overlap: int = 30,
    max_lag: int = 20,
) -> list[CrossdateHit]:
    """Slide sample vs reference by year lag; return hits sorted by |r| desc.

    lag > 0 means sample years are shifted later (sample too old / needs +lag on outer year).
    """
    if isinstance(sample, WidthSeries):
        samp = series_to_year_map(sample)
        sid = sample.sample_code
    else:
        samp = sample
        sid = "sample"

    if isinstance(reference, (str, Path)):
        all_ref = read_rwl(reference)
        if not all_ref:
            return []
        if reference_id and reference_id in all_ref:
            ref = all_ref[reference_id]
            rid = reference_id
        else:
            rid, ref = next(iter(all_ref.items()))
    else:
        ref = reference
        rid = reference_id or "ref"

    if not samp or not ref:
        return []

    hits: list[CrossdateHit] = []
    for lag in range(-max_lag, max_lag + 1):
        years = sorted(set(y + lag for y in samp) & set(ref))
        if len(years) < min_overlap:
            continue
        a = np.array([samp[y - lag] for y in years], dtype=np.float64)
        b = np.array([ref[y] for y in years], dtype=np.float64)
        # Drop zeros (missing)
        mask = (a > 0) & (b > 0)
        if int(mask.sum()) < min_overlap:
            continue
        r = _corr(a[mask], b[mask])
        hits.append(CrossdateHit(lag=lag, correlation=r, overlap=int(mask.sum()), reference_id=rid))
    hits.sort(key=lambda h: abs(h.correlation), reverse=True)
    return hits
