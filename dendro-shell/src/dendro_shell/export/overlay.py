"""PNG overlay of paths and ring ticks."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from dendro_shell.geometry import point_at_distance
from dendro_shell.project import Project


def render_overlay(project: Project, image: Image.Image | np.ndarray | None = None) -> Image.Image:
    if image is None:
        image = Image.open(project.image_path).convert("RGB")
    elif isinstance(image, np.ndarray):
        if image.ndim == 2:
            image = Image.fromarray(image, mode="L").convert("RGB")
        else:
            image = Image.fromarray(image[:, :, ::-1] if image.shape[2] == 3 else image).convert("RGB")
    else:
        image = image.convert("RGB")

    arr = np.asarray(image).copy()
    for mp in project.paths:
        pts = [(int(round(p.x)), int(round(p.y))) for p in mp.points]
        if len(pts) >= 2:
            cv2.polylines(arr, [np.array(pts, dtype=np.int32)], False, (40, 180, 220), 2, cv2.LINE_AA)
        for r in mp.rings:
            if r.flag == "false":
                continue
            pt = point_at_distance(mp.points, r.distance_px)
            color = (220, 80, 60) if r.flag == "ok" else (240, 200, 40)
            if r.flag == "missing":
                color = (180, 180, 180)
            cv2.circle(arr, (int(round(pt.x)), int(round(pt.y))), 4, color, -1, cv2.LINE_AA)
    if project.pith is not None:
        cv2.drawMarker(
            arr,
            (int(round(project.pith.x)), int(round(project.pith.y))),
            (80, 220, 120),
            markerType=cv2.MARKER_CROSS,
            markerSize=16,
            thickness=2,
        )
    return Image.fromarray(arr)


def save_overlay(project: Project, path: Path | str, image=None) -> Path:
    path = Path(path)
    render_overlay(project, image).save(path)
    return path
