"""High-level detect + export helpers used by CLI and UI."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from dendro_shell.detect.classical import detect_rings_along_path
from dendro_shell.export.overlay import save_overlay
from dendro_shell.export.pos import write_pos
from dendro_shell.export.rwl import write_rwl
from dendro_shell.geometry import (
    estimate_pith_center,
    path_length,
    radial_path_from_pith,
)
from dendro_shell.project import MeasurePath, Point, Project
from dendro_shell.series import assign_years, build_width_series
from dendro_shell.viz import render_report_png, render_skeleton_plot


def default_core_path(width: int, height: int) -> list[Point]:
    """Horizontal mid-line path for cores."""
    y = height / 2.0
    margin = width * 0.05
    return [Point(x=margin, y=y), Point(x=width - margin, y=y)]


def run_detect(
    image_path: Path | str,
    *,
    method: str = "classical",
    preset: str = "sanded_core",
    sample_type: str = "core",
    pith: Point | None = None,
    path_points: list[Point] | None = None,
    angle_deg: float = 0.0,
    min_distance_px: float = 12.0,
    prominence: float = 0.08,
    outer_year: int | None = None,
    sample_code: str = "",
) -> Project:
    image_path = Path(image_path)
    image = Image.open(image_path).convert("RGB")
    w, h = image.size

    if path_points is None:
        if sample_type == "disc":
            gray = preprocess_gray(image, preset)
            pith = pith or estimate_pith_center(gray)
            length = min(w, h) * 0.48
            path_points = radial_path_from_pith(pith, angle_deg, length)
        else:
            path_points = default_core_path(w, h)

    if method == "unet":
        from dendro_shell.detect.unet import detect_rings_unet

        result = detect_rings_unet(
            image,
            path_points,
            preset=preset,
            min_distance_px=min_distance_px,
            prominence=prominence,
        )
    else:
        result = detect_rings_along_path(
            image,
            path_points,
            preset=preset,
            min_distance_px=min_distance_px,
            prominence=prominence,
        )

    rings = result.rings
    if outer_year is not None:
        rings = assign_years(rings, outer_year)

    project = Project(
        image_path=str(image_path.resolve()),
        sample_code=sample_code or image_path.stem,
        sample_type=sample_type,  # type: ignore[arg-type]
        preprocess_preset=preset,
        detect_method=method if method in ("classical", "unet") else "classical",  # type: ignore[arg-type]
        outer_year=outer_year,
        pith=pith,
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
