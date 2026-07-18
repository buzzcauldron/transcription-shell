"""PNG overlay of paths and ring ticks (confidence-styled)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from dendro_shell.project import Project
from dendro_shell.viz import render_confidence_overlay


def render_overlay(project: Project, image: Image.Image | None = None) -> Image.Image:
    return render_confidence_overlay(project, image)


def save_overlay(project: Project, path: Path | str, image=None) -> Path:
    path = Path(path)
    render_overlay(project, image).save(path)
    return path
