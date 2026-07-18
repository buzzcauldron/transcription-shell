"""High-level detect + export helpers used by CLI and UI."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from dendro_shell.detect.classical import detect_rings_along_path, infer_sample_type
from dendro_shell.export.overlay import save_overlay
from dendro_shell.export.pos import write_pos
from dendro_shell.export.rwl import write_rwl
from dendro_shell.geometry import (
    estimate_pith_center,
    path_length,
)
from dendro_shell.preprocess import preprocess_gray
from dendro_shell.project import MeasurePath, Point, Project
from dendro_shell.series import assign_years, build_width_series
from dendro_shell.viz import render_report_png, render_skeleton_plot


def default_core_path(width: int, height: int) -> list[Point]:
    """Horizontal mid-line path for cores / rectangular cuts."""
    y = height / 2.0
    margin = width * 0.04
    return [Point(x=margin, y=y), Point(x=width - margin, y=y)]


def diameter_path_from_pith(
    pith: Point,
    width: int,
    height: int,
    angle_deg: float = 0.0,
    margin: float = 8.0,
) -> list[Point]:
    """Full bark-to-bark diameter through pith (standard disc transect)."""
    ang = math.radians(angle_deg)
    dx, dy = math.cos(ang), math.sin(ang)
    # Ray-box intersection both directions
    candidates = []
    for sign in (-1.0, 1.0):
        t_vals = []
        if abs(dx) > 1e-9:
            t_vals.append((margin - pith.x) / (sign * dx))
            t_vals.append((width - 1 - margin - pith.x) / (sign * dx))
        if abs(dy) > 1e-9:
            t_vals.append((margin - pith.y) / (sign * dy))
            t_vals.append((height - 1 - margin - pith.y) / (sign * dy))
        t_pos = [t for t in t_vals if t > 0]
        t = min(t_pos) if t_pos else min(width, height) * 0.4
        candidates.append(
            Point(x=pith.x + sign * dx * t, y=pith.y + sign * dy * t)
        )
    # Order so path crosses pith: start → pith → end
    a, b = candidates
    return [a, Point(x=pith.x, y=pith.y), b]


def run_detect(
    image_path: Path | str,
    *,
    method: str = "classical",
    preset: str | None = None,
    sample_type: str | None = None,
    pith: Point | None = None,
    path_points: list[Point] | None = None,
    angle_deg: float = 0.0,
    min_distance_px: float | None = None,
    prominence: float | None = None,
    outer_year: int | None = None,
    sample_code: str = "",
    auto: bool = True,
) -> Project:
    image_path = Path(image_path)
    image = Image.open(image_path).convert("RGB")
    w, h = image.size

    if sample_type in (None, "", "auto") and auto:
        sample_type = infer_sample_type(image)
    sample_type = sample_type or "core"

    if preset in (None, "", "auto"):
        preset = "dark_disc" if sample_type == "disc" else "sanded_core"

    if path_points is None or len(path_points) < 2:
        if sample_type == "disc":
            gray = preprocess_gray(image, preset)
            pith = pith or estimate_pith_center(gray)
            path_points = diameter_path_from_pith(pith, w, h, angle_deg=angle_deg)
        else:
            path_points = default_core_path(w, h)

    bridge_meta: dict | None = None
    if method == "unet":
        from dendro_shell.detect.unet import detect_rings_unet

        result = detect_rings_unet(
            image,
            path_points,
            preset=preset,
            min_distance_px=min_distance_px or 8.0,
            prominence=prominence or 0.06,
        )
        rings = result.rings
    elif method == "boolean":
        from dendro_shell.detect.boolean_bridge import detect_rings_boolean_bridge

        if pith is None and sample_type == "disc":
            pith = estimate_pith_center(preprocess_gray(image, preset))
        # For cores without pith, use path midpoint as pseudo-pith for radius matching
        if pith is None:
            mid = path_points[len(path_points) // 2]
            pith = Point(x=mid.x, y=mid.y)
        bres = detect_rings_boolean_bridge(
            image,
            path_points,
            pith=pith,
            preset=preset,
        )
        rings = bres.rings
        bridge_meta = {
            "n_bridged": sum(1 for b in bres.bridged if b.crossed_break),
            "n_matched": len(bres.bridged),
            "break_fraction": float(np.mean(bres.break_mask > 0)),
        }
    else:
        result = detect_rings_along_path(
            image,
            path_points,
            preset=preset,
            min_distance_px=min_distance_px,
            prominence=prominence,
        )
        rings = result.rings

    if outer_year is None and rings:
        # Usable chronology out of the box; user can edit outer year in UI
        outer_year = datetime.now().year
    if outer_year is not None:
        rings = assign_years(rings, outer_year)

    notes = ""
    if bridge_meta:
        notes = (
            f"boolean_bridge: matched={bridge_meta['n_matched']} "
            f"bridged_over_breaks={bridge_meta['n_bridged']} "
            f"break_frac={bridge_meta['break_fraction']:.3f}"
        )

    project = Project(
        image_path=str(image_path.resolve()),
        sample_code=sample_code or image_path.stem,
        sample_type=sample_type,  # type: ignore[arg-type]
        preprocess_preset=preset,
        detect_method=method if method in ("classical", "unet", "boolean") else "classical",  # type: ignore[arg-type]
        outer_year=outer_year,
        pith=pith,
        notes=notes,
        paths=[MeasurePath(id="path0", points=list(path_points), rings=rings)],
    )
    return project


def export_all(project: Project, out_dir: Path | str) -> dict[str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    project.save(out_dir / "project.json")
    series = build_width_series(project)
    stem = project.sample_code or "series"
    write_rwl(series, out_dir / f"{stem}.rwl")
    write_pos(project, out_dir / f"{stem}.pos")
    save_overlay(project, out_dir / "overlay.png")
    render_skeleton_plot(series).save(out_dir / "skeleton.png")
    render_report_png(project, out_dir / "report.png")
    result = {
        "project": str(out_dir / "project.json"),
        "rwl": str(out_dir / f"{stem}.rwl"),
        "pos": str(out_dir / f"{stem}.pos"),
        "overlay": str(out_dir / "overlay.png"),
        "skeleton": str(out_dir / "skeleton.png"),
        "report": str(out_dir / "report.png"),
        "n_rings": str(sum(len(p.rings) for p in project.paths)),
        "path_length_px": str(
            path_length(project.paths[0].points) if project.paths else 0
        ),
    }
    if project.sample_type == "disc" and project.pith is not None:
        import json

        from dendro_shell.contours import contours_to_geojson

        geo = out_dir / "rings.geojson"
        geo.write_text(json.dumps(contours_to_geojson(project), indent=2), encoding="utf-8")
        result["contours"] = str(geo)
    return result
