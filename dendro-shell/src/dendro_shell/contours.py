"""Second-class closed ring contours for discs (from pith + radial ticks)."""

from __future__ import annotations

import math

import numpy as np

from dendro_shell.geometry import path_length, point_at_distance, radial_path_from_pith
from dendro_shell.project import Point, Project, RingTick


def closed_rings_from_project(
    project: Project,
    *,
    n_angles: int = 36,
) -> list[list[Point]]:
    """Approximate closed contours by sampling radial distances at several angles.

    Uses the primary path's ring distances as radii from pith. When only one
    radial transect exists, contours are circles at those radii (useful viz /
    export, not full CS-TRD delineation).
    """
    if project.pith is None or not project.paths:
        return []
    pith = project.pith
    primary = project.paths[0]
    rings = [r for r in primary.rings if r.flag not in ("false",)]
    if not rings:
        return []

    contours: list[list[Point]] = []
    for r in sorted(rings, key=lambda t: t.distance_px):
        radius = float(r.distance_px)
        pts: list[Point] = []
        for i in range(n_angles):
            ang = 2 * math.pi * i / n_angles
            pts.append(
                Point(
                    x=pith.x + radius * math.cos(ang),
                    y=pith.y + radius * math.sin(ang),
                )
            )
        pts.append(pts[0])  # close
        contours.append(pts)
    return contours


def contours_to_geojson(project: Project) -> dict:
    feats = []
    for i, ring in enumerate(closed_rings_from_project(project)):
        coords = [[p.x, p.y] for p in ring]
        feats.append(
            {
                "type": "Feature",
                "properties": {"ring_index": i, "sample": project.sample_code},
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        )
    return {"type": "FeatureCollection", "features": feats}
