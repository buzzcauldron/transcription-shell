"""Classical 1D profile peak picking along a measurement path."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks, savgol_filter

from dendro_shell.geometry import PathSample, sample_profile
from dendro_shell.preprocess import preprocess_gray
from dendro_shell.project import Point, RingTick


@dataclass
class DetectResult:
    rings: list[RingTick]
    profile: np.ndarray
    sample: PathSample
    edge_strength: np.ndarray


def _edge_strength(profile: np.ndarray, window: int = 11) -> np.ndarray:
    """Score ring boundaries: prefer dark latewood troughs over raw gradient peaks.

    Using inverted smoothed intensity as the primary signal avoids double-counting
    both flanks of a latewood band (common failure mode on sanded cores).
    """
    n = len(profile)
    if n < 5:
        return np.zeros(n, dtype=np.float64)
    w = min(window, n if n % 2 == 1 else n - 1)
    w = max(5, w | 1)
    poly = 2 if w > 2 else 1
    try:
        smooth = savgol_filter(profile.astype(np.float64), w, poly)
    except ValueError:
        smooth = profile.astype(np.float64)
    inv = (smooth.max() - smooth) if smooth.max() > smooth.min() else np.zeros_like(smooth)
    inv = inv / (inv.max() + 1e-8)
    grad = np.abs(np.gradient(smooth))
    grad = grad / (grad.max() + 1e-8)
    # Emphasize troughs; light gradient assist for faint rings
    return 0.75 * inv + 0.25 * grad


def detect_rings_along_path(
    image,
    path_points: list[Point] | list[tuple[float, float]],
    *,
    preset: str = "sanded_core",
    min_distance_px: float = 8.0,
    prominence: float = 0.08,
    half_width: int = 4,
    probability: np.ndarray | None = None,
) -> DetectResult:
    """Detect ring ticks along a path.

    If ``probability`` (same shape as image, 0..1 boundary map) is given,
    sample that instead of classical edge strength from intensity.
    """
    gray = preprocess_gray(image, preset)
    if probability is not None:
        profile, sample = sample_profile(probability.astype(np.float64), path_points, half_width=half_width)
        strength = profile / (profile.max() + 1e-8)
    else:
        profile, sample = sample_profile(gray, path_points, half_width=half_width)
        strength = _edge_strength(profile)

    if len(strength) < 3:
        return DetectResult([], profile, sample, strength)

    distance = max(1, int(round(min_distance_px)))
    peaks, props = find_peaks(strength, distance=distance, prominence=prominence)
    if len(peaks) == 0:
        # Relax once for hard images
        peaks, props = find_peaks(strength, distance=max(1, distance // 2), prominence=prominence * 0.5)

    prom = props.get("prominences", np.ones(len(peaks)))
    prom_max = float(np.max(prom)) if len(prom) else 1.0
    rings: list[RingTick] = []
    for pk, pr in zip(peaks, prom):
        dist = float(sample.distances[int(pk)])
        conf = float(np.clip(pr / (prom_max + 1e-8), 0.05, 1.0))
        rings.append(RingTick(distance_px=dist, confidence=conf, flag="ok"))
    # Outer (bark) end first for chronology labeling convenience: sort descending distance
    rings.sort(key=lambda r: r.distance_px, reverse=True)
    return DetectResult(rings=rings, profile=profile, sample=sample, edge_strength=strength)


def detect_on_polar_mean(
    polar: np.ndarray,
    *,
    min_distance_px: float = 8.0,
    prominence: float = 0.08,
) -> list[float]:
    """Mean across angles → peaks in radius (distance from pith)."""
    profile = np.mean(polar.astype(np.float64), axis=0)
    strength = _edge_strength(profile)
    distance = max(1, int(round(min_distance_px)))
    peaks, _ = find_peaks(strength, distance=distance, prominence=prominence)
    return [float(p) for p in peaks]
