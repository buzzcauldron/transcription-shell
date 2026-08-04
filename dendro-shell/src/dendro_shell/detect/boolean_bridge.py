"""Boolean ring matching across cracks, checks, and damaged zones.

Pipeline:
1. Build a binary latewood / ring-edge map.
2. Build a binary break mask (radial cracks, bright fissures).
3. Detect fragments with ``ring_map & ~break_mask``.
4. Match fragments into whole rings with a Boolean radius predicate
   (same ring if |r_a - r_b| ≤ tol), then morphologically close gaps
   in polar space so a measurement path can recover bridged ticks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.signal import find_peaks

from dendro_shell.detect.classical import DetectResult, _adaptive_min_distance, _edge_strength
from dendro_shell.geometry import (
    PathSample,
    estimate_pith_center,
    polar_unwrap,
    sample_profile,
)
from dendro_shell.preprocess import preprocess_gray
from dendro_shell.project import Point, RingTick


@dataclass
class BridgeInfo:
    """Diagnostics for one bridged ring tick."""

    distance_px: float
    radius_px: float
    n_fragments: int
    crossed_break: bool
    match_score: float


@dataclass
class BooleanBridgeResult:
    rings: list[RingTick]
    break_mask: np.ndarray
    ring_map: np.ndarray
    bridged: list[BridgeInfo] = field(default_factory=list)
    profile: np.ndarray | None = None
    sample: PathSample | None = None
    edge_strength: np.ndarray | None = None


def detect_break_mask(gray: np.ndarray, *, pith: Point | None = None) -> np.ndarray:
    """Binary mask of cracks / checks / bright damage corridors.

    Combines:
    - bright fissures (high local intensity after invert of dark rings)
    - strong radial edges (likely shake/check walls)
    """
    h, w = gray.shape[:2]
    # Bright gaps (checks often appear white/bright in scans)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
    bright = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, -8
    )
    # Dark wide cracks
    dark = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12
    )
    # Thin bright lines via morphological top-hat
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    tophat = cv2.morphologyEx(blur, cv2.MORPH_TOPHAT, kernel)
    _, th = cv2.threshold(tophat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    breaks = cv2.bitwise_or(bright, dark)
    breaks = cv2.bitwise_or(breaks, th)

    # Prefer elongated radial structures when pith is known
    if pith is not None:
        yy, xx = np.mgrid[0:h, 0:w]
        ang = np.arctan2(yy - pith.y, xx - pith.x)
        # Radial gradient energy
        gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
        # Direction of gradient vs tangential → crack walls often radial
        tx, ty = -np.sin(ang), np.cos(ang)
        tangential = np.abs(gx * tx + gy * ty)
        radial = np.abs(gx * np.cos(ang) + gy * np.sin(ang))
        ratio = tangential / (radial + 1e-3)
        radial_pref = (ratio > 1.4).astype(np.uint8) * 255
        breaks = cv2.bitwise_and(breaks, cv2.bitwise_or(radial_pref, th))

    # Clean speckles; keep elongated structures
    breaks = cv2.morphologyEx(breaks, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    breaks = cv2.morphologyEx(
        breaks, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    )
    return breaks


def detect_ring_map(gray: np.ndarray) -> np.ndarray:
    """Binary latewood / ring-boundary map."""
    blur = cv2.GaussianBlur(gray, (0, 0), 0.8)
    # Dark latewood
    inv = cv2.bitwise_not(blur)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enh = clahe.apply(inv)
    edges = cv2.Canny(enh, 40, 120)
    # Also Otsu on inverted for thick latewood
    _, otsu = cv2.threshold(enh, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ring = cv2.bitwise_or(edges, cv2.morphologyEx(otsu, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)))
    ring = cv2.dilate(ring, np.ones((2, 2), np.uint8), iterations=1)
    return ring


def boolean_same_ring(r_a: float, r_b: float, tol: float) -> bool:
    """Boolean predicate: fragments belong to the same annual ring."""
    return abs(r_a - r_b) <= tol


def _polar_close_rings(
    ring_map: np.ndarray,
    break_mask: np.ndarray,
    pith: Point,
    *,
    close_px: int = 12,
) -> np.ndarray:
    """Close ring gaps across breaks in polar space (angular neighborhood)."""
    # Suppress breaks, then close along angle axis
    clean = cv2.bitwise_and(ring_map, cv2.bitwise_not(break_mask))
    polar = polar_unwrap(clean, pith, n_angles=360)
    # Close along columns (radius) lightly and rows (angle) more — bridges radial cracks
    k_ang = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, close_px)))
    closed = cv2.morphologyEx(polar, cv2.MORPH_CLOSE, k_ang)
    k_rad = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
    closed = cv2.morphologyEx(closed, cv2.MORPH_CLOSE, k_rad)
    # Map back approx by polar remap inverse is expensive; return polar for radius peaks
    return closed


def _radii_from_polar(polar_closed: np.ndarray, *, min_distance: int = 4) -> list[float]:
    """Consensus ring radii from angle-mean of closed polar ring map."""
    profile = np.mean(polar_closed.astype(np.float64), axis=0)
    if profile.max() <= 0:
        return []
    strength = profile / (profile.max() + 1e-8)
    # Also boost with classical trough-style on inverted mean intensity if needed
    peaks, props = find_peaks(strength, distance=max(2, min_distance), prominence=0.05)
    if len(peaks) < 3:
        peaks, props = find_peaks(strength, distance=max(2, min_distance // 2), prominence=0.02)
    return [float(p) for p in peaks]


def _match_path_peaks_to_radii(
    path_points: list[Point],
    pith: Point,
    radii: list[float],
    gray: np.ndarray,
    break_mask: np.ndarray,
    *,
    tol: float,
) -> tuple[list[RingTick], list[BridgeInfo], np.ndarray, PathSample, np.ndarray]:
    """Place ticks on the measure path by Boolean-matching to consensus radii."""
    profile, sample = sample_profile(gray, path_points, half_width=5)
    # Break encounters along path
    br_prof, _ = sample_profile(break_mask.astype(np.float64), path_points, half_width=2)
    in_break = br_prof > 127

    strength = _edge_strength(profile)
    # Local peaks for confidence, but primary placement from matched radii
    distance = _adaptive_min_distance(strength, max(4.0, len(strength) / 80.0))
    local_peaks, local_props = find_peaks(strength, distance=distance, prominence=0.04)
    local_d = {float(sample.distances[int(pk)]): float(pr)
               for pk, pr in zip(local_peaks, local_props.get("prominences", np.ones(len(local_peaks))))}

    rings: list[RingTick] = []
    bridged: list[BridgeInfo] = []
    # Path geometry → map distance along path to radius from pith
    # For each consensus radius, find path sample point nearest that radius
    xs, ys, dists = sample.xs, sample.ys, sample.distances
    path_r = np.hypot(xs - pith.x, ys - pith.y)

    for radius in sorted(radii):
        # Candidates: path samples with |path_r - radius| ≤ tol
        ok = np.where(np.abs(path_r - radius) <= tol)[0]
        if len(ok) == 0:
            # widen once
            ok = np.where(np.abs(path_r - radius) <= tol * 1.8)[0]
        if len(ok) == 0:
            continue
        # Prefer non-break samples; else allow bridge
        non_break = [i for i in ok if not in_break[min(i, len(in_break) - 1)]]
        crossed = len(non_break) == 0
        pool = non_break if non_break else list(ok)
        # Choose sample closest in radius, then highest local strength
        best_i = min(pool, key=lambda i: (abs(path_r[i] - radius), -strength[i]))
        dist_px = float(dists[best_i])

        # Boolean match to any local peak
        matched_local = False
        conf = 0.35
        for ld, lp in local_d.items():
            if boolean_same_ring(ld, dist_px, tol):
                matched_local = True
                conf = float(np.clip(0.5 + 0.5 * (lp / (max(local_d.values()) + 1e-8)), 0.2, 1.0))
                dist_px = ld  # snap to measured peak when compatible
                break
        if crossed:
            conf *= 0.7
        flag = "uncertain" if crossed and not matched_local else "ok"
        rings.append(
            RingTick(
                distance_px=dist_px,
                confidence=conf,
                flag=flag,  # type: ignore[arg-type]
                note="bridged" if crossed else ("matched" if matched_local else "polar"),
            )
        )
        bridged.append(
            BridgeInfo(
                distance_px=dist_px,
                radius_px=radius,
                n_fragments=1 + int(matched_local),
                crossed_break=crossed,
                match_score=conf,
            )
        )

    rings.sort(key=lambda r: r.distance_px, reverse=True)
    # Deduplicate nearly-identical distances (Boolean collapse)
    deduped: list[RingTick] = []
    for r in rings:
        if deduped and boolean_same_ring(deduped[-1].distance_px, r.distance_px, tol * 0.5):
            if r.confidence > deduped[-1].confidence:
                deduped[-1] = r
            continue
        deduped.append(r)
    return deduped, bridged, profile, sample, strength


def detect_rings_boolean_bridge(
    image,
    path_points: list[Point],
    *,
    pith: Point | None = None,
    preset: str = "dark_disc",
    radius_tol_px: float | None = None,
    close_px: int = 14,
) -> BooleanBridgeResult:
    """Full Boolean bridge detect for a path on a (possibly damaged) disc/core."""
    gray = preprocess_gray(image, preset)
    if pith is None:
        pith = estimate_pith_center(gray)

    ring_map = detect_ring_map(gray)
    break_mask = detect_break_mask(gray, pith=pith)

    # Fragment map (Boolean AND NOT)
    fragments = cv2.bitwise_and(ring_map, cv2.bitwise_not(break_mask))

    polar_closed = _polar_close_rings(ring_map, break_mask, pith, close_px=close_px)
    # Adaptive tol from image scale
    h, w = gray.shape[:2]
    tol = float(radius_tol_px) if radius_tol_px is not None else max(3.0, min(w, h) * 0.006)

    radii = _radii_from_polar(polar_closed, min_distance=max(3, int(tol)))
    if len(radii) < 2:
        # Fallback: classical peaks ignoring breaks, then still mark break crossings
        profile, sample = sample_profile(gray, path_points, half_width=5)
        strength = _edge_strength(profile)
        dist = _adaptive_min_distance(strength, 6.0)
        peaks, props = find_peaks(strength, distance=dist, prominence=0.04)
        rings = [
            RingTick(
                distance_px=float(sample.distances[int(pk)]),
                confidence=float(pr / (max(props.get("prominences", [1])) + 1e-8)),
                flag="ok",
                note="fallback",
            )
            for pk, pr in zip(peaks, props.get("prominences", np.ones(len(peaks))))
        ]
        rings.sort(key=lambda r: r.distance_px, reverse=True)
        return BooleanBridgeResult(
            rings=rings,
            break_mask=break_mask,
            ring_map=fragments,
            bridged=[],
            profile=profile,
            sample=sample,
            edge_strength=strength,
        )

    rings, bridged, profile, sample, strength = _match_path_peaks_to_radii(
        path_points, pith, radii, gray, break_mask, tol=tol
    )
    return BooleanBridgeResult(
        rings=rings,
        break_mask=break_mask,
        ring_map=fragments,
        bridged=bridged,
        profile=profile,
        sample=sample,
        edge_strength=strength,
    )


def to_detect_result(result: BooleanBridgeResult) -> DetectResult:
    return DetectResult(
        rings=result.rings,
        profile=result.profile if result.profile is not None else np.zeros(0),
        sample=result.sample if result.sample is not None else PathSample(
            np.zeros(0), np.zeros(0), np.zeros(0), 0.0
        ),
        edge_strength=result.edge_strength if result.edge_strength is not None else np.zeros(0),
    )
