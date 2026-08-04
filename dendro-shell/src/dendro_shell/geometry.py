"""Pith, paths, polar unwrap, and scale helpers."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from dendro_shell.project import Point, ScaleInfo


@dataclass
class PathSample:
    """Resampled points along a polyline with cumulative distances."""

    xs: np.ndarray
    ys: np.ndarray
    distances: np.ndarray  # cumulative px from start
    total_length: float


def path_length(points: list[Point] | list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    arr = _as_xy(points)
    d = np.sqrt(np.sum(np.diff(arr, axis=0) ** 2, axis=1))
    return float(np.sum(d))


def _as_xy(points: list[Point] | list[tuple[float, float]]) -> np.ndarray:
    out = []
    for p in points:
        if isinstance(p, Point):
            out.append((p.x, p.y))
        else:
            out.append((float(p[0]), float(p[1])))
    return np.asarray(out, dtype=np.float64)


def resample_path(
    points: list[Point] | list[tuple[float, float]],
    step_px: float = 1.0,
) -> PathSample:
    arr = _as_xy(points)
    if len(arr) == 0:
        z = np.zeros(0, dtype=np.float64)
        return PathSample(z, z, z, 0.0)
    if len(arr) == 1:
        return PathSample(arr[:, 0], arr[:, 1], np.array([0.0]), 0.0)
    seg = np.sqrt(np.sum(np.diff(arr, axis=0) ** 2, axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total <= 0:
        return PathSample(arr[:1, 0], arr[:1, 1], np.array([0.0]), 0.0)
    n = max(2, int(np.ceil(total / max(step_px, 1e-6))) + 1)
    targets = np.linspace(0.0, total, n)
    xs = np.interp(targets, cum, arr[:, 0])
    ys = np.interp(targets, cum, arr[:, 1])
    return PathSample(xs, ys, targets, total)


def sample_profile(
    gray: np.ndarray,
    points: list[Point] | list[tuple[float, float]],
    half_width: int = 3,
    step_px: float = 1.0,
) -> tuple[np.ndarray, PathSample]:
    """Mean intensity in a strip around the path."""
    sample = resample_path(points, step_px=step_px)
    h, w = gray.shape[:2]
    profile = np.zeros(len(sample.distances), dtype=np.float64)
    for i, (x, y) in enumerate(zip(sample.xs, sample.ys)):
        x0 = int(round(x))
        y0 = int(round(y))
        x1 = max(0, x0 - half_width)
        x2 = min(w, x0 + half_width + 1)
        y1 = max(0, y0 - half_width)
        y2 = min(h, y0 + half_width + 1)
        patch = gray[y1:y2, x1:x2]
        profile[i] = float(np.mean(patch)) if patch.size else 0.0
    return profile, sample


def point_at_distance(
    points: list[Point] | list[tuple[float, float]],
    distance_px: float,
) -> Point:
    sample = resample_path(points, step_px=1.0)
    if len(sample.distances) == 0:
        return Point(x=0.0, y=0.0)
    d = float(np.clip(distance_px, 0.0, sample.total_length))
    x = float(np.interp(d, sample.distances, sample.xs))
    y = float(np.interp(d, sample.distances, sample.ys))
    return Point(x=x, y=y)


def estimate_pith_center(gray: np.ndarray) -> Point:
    """Cheap intensity-center fallback for disc pith."""
    blur = cv2.GaussianBlur(gray, (0, 0), 5)
    # Prefer darker pith-like centers on light wood; also try inverted
    _, thr = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ys, xs = np.nonzero(thr)
    if len(xs) < 10:
        h, w = gray.shape[:2]
        return Point(x=w / 2.0, y=h / 2.0)
    return Point(x=float(np.mean(xs)), y=float(np.mean(ys)))


def radial_path_from_pith(
    pith: Point,
    angle_deg: float,
    length_px: float,
    n_points: int = 64,
) -> list[Point]:
    ang = np.deg2rad(angle_deg)
    pts = []
    for t in np.linspace(0.0, 1.0, n_points):
        r = t * length_px
        pts.append(Point(x=pith.x + r * np.cos(ang), y=pith.y + r * np.sin(ang)))
    return pts


def polar_unwrap(
    gray: np.ndarray,
    pith: Point,
    max_radius: float | None = None,
    n_angles: int = 360,
    n_radii: int | None = None,
) -> np.ndarray:
    """Unwrap disc so rings become near-horizontal ridges. Shape (n_angles, n_radii)."""
    h, w = gray.shape[:2]
    if max_radius is None:
        corners = np.array(
            [[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]], dtype=np.float64
        )
        d = np.sqrt((corners[:, 0] - pith.x) ** 2 + (corners[:, 1] - pith.y) ** 2)
        max_radius = float(np.max(d))
    if n_radii is None:
        n_radii = int(max(32, round(max_radius)))
    map_x = np.zeros((n_angles, n_radii), dtype=np.float32)
    map_y = np.zeros((n_angles, n_radii), dtype=np.float32)
    angles = np.linspace(0, 2 * np.pi, n_angles, endpoint=False)
    radii = np.linspace(0, max_radius, n_radii)
    for i, a in enumerate(angles):
        map_x[i] = pith.x + radii * np.cos(a)
        map_y[i] = pith.y + radii * np.sin(a)
    return cv2.remap(
        gray,
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


_UNIT_TO_UM = {"um": 1.0, "mm": 1000.0, "cm": 10000.0}


def micrometers_per_pixel(scale: ScaleInfo) -> float | None:
    if scale.micrometers_per_pixel is not None:
        return float(scale.micrometers_per_pixel)
    if scale.p1 and scale.p2 and scale.known_length and scale.known_unit:
        dx = scale.p2.x - scale.p1.x
        dy = scale.p2.y - scale.p1.y
        px = float(np.hypot(dx, dy))
        if px <= 0:
            return None
        um = float(scale.known_length) * _UNIT_TO_UM[scale.known_unit]
        return um / px
    return None


def calibrate_scale(
    p1: Point,
    p2: Point,
    known_length: float,
    known_unit: str = "mm",
) -> ScaleInfo:
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    px = float(np.hypot(dx, dy))
    um = float(known_length) * _UNIT_TO_UM[known_unit]
    mpp = um / px if px > 0 else None
    return ScaleInfo(
        micrometers_per_pixel=mpp,
        unit="um",
        p1=p1,
        p2=p2,
        known_length=known_length,
        known_unit=known_unit,  # type: ignore[arg-type]
    )
