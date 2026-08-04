"""CooRecorder-compatible .pos writer (simplified)."""

from __future__ import annotations

from pathlib import Path

from dendro_shell.geometry import micrometers_per_pixel, point_at_distance
from dendro_shell.project import MeasurePath, Project


def write_pos(project: Project, path: Path | str, measure_path: MeasurePath | None = None) -> None:
    """Write a simple .POS with scale and point coordinates along the path.

    Format loosely follows CooRecorder: header comments + coordinate pairs.
    """
    path = Path(path)
    mp = measure_path or project.primary_path()
    if mp is None:
        path.write_text("# empty\n", encoding="utf-8")
        return
    mpp = micrometers_per_pixel(project.scale)
    scale_mm = (mpp / 1000.0) if mpp else 0.0
    lines = [
        f"#DENDRO {project.sample_code}",
        f"#SCALE {scale_mm:.6f}",  # mm per pixel
        f"#IMAGE {project.image_path}",
        "#POINTS",
    ]
    ordered = sorted(mp.rings, key=lambda r: r.distance_px, reverse=True)
    for r in ordered:
        if r.flag == "false":
            continue
        pt = point_at_distance(mp.points, r.distance_px)
        year = r.year if r.year is not None else -1
        lines.append(f"{pt.x:.3f},{pt.y:.3f},{year},{r.flag}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
