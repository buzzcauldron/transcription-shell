"""Classical 1D profile peak picking along a measurement path."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy.signal import find_peaks, savgol_filter

from dendro_shell.geometry import PathSample, resample_path, sample_profile
from dendro_shell.preprocess import preprocess_gray
from dendro_shell.project import Point, RingTick


@dataclass
class DetectResult:
    rings: list[RingTick]
    profile: np.ndarray
    sample: PathSample
    edge_strength: np.ndarray


def infer_sample_type(image) -> str:
    """Guess core vs disc from dominant edge orientation.

    Vertical latewood bands (typical sanded core / rectangular cut) → core.
    More isotropic / circular structure → disc.
    """
    gray = preprocess_gray(image, "sanded_core")
    h, w = gray.shape[:2]
    # center crop to avoid bark/background
    y0, y1 = int(h * 0.2), int(h * 0.8)
    x0, x1 = int(w * 0.2), int(w * 0.8)
    crop = gray[y0:y1, x0:x1]
    gx = cv2.Sobel(crop, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(crop, cv2.CV_32F, 0, 1, ksize=3)
    ax, ay = float(np.mean(np.abs(gx))), float(np.mean(np.abs(gy)))
    if ax > 1.25 * ay:
        return "core"
    if ay > 1.25 * ax:
        return "core"  # horizontal bands — still linear transect
    return "disc"


def _smooth(profile: np.ndarray, window: int = 11) -> np.ndarray:
    n = len(profile)
    if n < 5:
        return profile.astype(np.float64)
    w = min(window, n if n % 2 == 1 else n - 1)
    w = max(5, w | 1)
    try:
        return savgol_filter(profile.astype(np.float64), w, 2)
    except ValueError:
        return profile.astype(np.float64)


def _edge_strength(profile: np.ndarray, window: int = 11) -> np.ndarray:
    """Score ring boundaries: dark latewood troughs + gradient assist."""
    smooth = _smooth(profile, window)
    if smooth.max() <= smooth.min():
        return np.zeros_like(smooth)
    inv = (smooth.max() - smooth) / (smooth.max() - smooth.min() + 1e-8)
    grad = np.abs(np.gradient(smooth))
    grad = grad / (grad.max() + 1e-8)
    return 0.8 * inv + 0.2 * grad


def _enhance_path_neighborhood(
    gray: np.ndarray,
    path_points: list[Point] | list[tuple[float, float]],
    *,
    half_width: int = 28,
) -> np.ndarray:
    """Local CLAHE along the path strip (HTR per-crop idea)."""
    out = gray.copy()
    sample = resample_path(path_points, step_px=2.0)
    h, w = gray.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for x, y in zip(sample.xs, sample.ys):
        cv2.circle(mask, (int(round(x)), int(round(y))), half_width, 255, -1)
    if not mask.any():
        return out
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4))
    local = clahe.apply(gray)
    return np.where(mask > 0, local, out).astype(np.uint8)


def _adaptive_min_distance(strength: np.ndarray, fallback: float) -> int:
    """Estimate typical ring spacing from autocorrelation; clamp sensibly."""
    n = len(strength)
    if n < 32:
        return max(1, int(round(fallback)))
    x = strength - strength.mean()
    corr = np.correlate(x, x, mode="full")[n - 1 :]
    corr = corr / (corr[0] + 1e-8)
    # first meaningful peak after lag 3
    peaks, _ = find_peaks(corr[3 : max(4, n // 3)], height=0.15, distance=3)
    if len(peaks):
        lag = int(peaks[0] + 3)
        return max(3, min(lag, int(n // 8)))
    return max(3, int(round(fallback)))


def detect_rings_along_path(
    image,
    path_points: list[Point] | list[tuple[float, float]],
    *,
    preset: str = "sanded_core",
    min_distance_px: float | None = None,
    prominence: float | None = None,
    half_width: int = 5,
    probability: np.ndarray | None = None,
    path_neighborhood: bool = True,
) -> DetectResult:
    """Detect ring ticks along a path with adaptive spacing/prominence."""
    gray = preprocess_gray(image, preset)
    if probability is not None:
        profile, sample = sample_profile(
            probability.astype(np.float64), path_points, half_width=half_width
        )
        strength = profile / (profile.max() + 1e-8)
    else:
        if path_neighborhood and path_points:
            gray = _enhance_path_neighborhood(gray, path_points)
        profile, sample = sample_profile(gray, path_points, half_width=half_width)
        strength = _edge_strength(profile)

    if len(strength) < 3:
        return DetectResult([], profile, sample, strength)

    # Prefer intensity minima (latewood) as primary peak source
    smooth = _smooth(profile)
    trough_score = (smooth.max() - smooth) / (smooth.max() - smooth.min() + 1e-8)
    score = 0.65 * trough_score + 0.35 * strength

    fb = float(min_distance_px) if min_distance_px is not None else max(4.0, len(score) / 80.0)
    distance = _adaptive_min_distance(score, fb)
    prom = float(prominence) if prominence is not None else 0.06

    peaks, props = find_peaks(score, distance=distance, prominence=prom)
    if len(peaks) < 3:
        peaks, props = find_peaks(
            score, distance=max(2, distance // 2), prominence=max(0.02, prom * 0.4)
        )
    if len(peaks) < 2:
        # last resort: local minima of intensity
        peaks, props = find_peaks(
            -smooth, distance=max(2, distance // 2), prominence=(smooth.max() - smooth.min()) * 0.03
        )

    prom_vals = props.get("prominences", np.ones(len(peaks)))
    prom_max = float(np.max(prom_vals)) if len(prom_vals) else 1.0
    rings: list[RingTick] = []
    for pk, pr in zip(peaks, prom_vals):
        dist = float(sample.distances[int(pk)])
        # skip near path ends (bark/background noise)
        if dist < 2 or dist > sample.total_length - 2:
            continue
        conf = float(np.clip(pr / (prom_max + 1e-8), 0.05, 1.0))
        rings.append(RingTick(distance_px=dist, confidence=conf, flag="ok"))
    rings.sort(key=lambda r: r.distance_px, reverse=True)
    return DetectResult(rings=rings, profile=profile, sample=sample, edge_strength=score)


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
