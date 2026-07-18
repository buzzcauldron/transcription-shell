"""Project JSON bundle helpers."""

from __future__ import annotations

import shutil
from pathlib import Path

from dendro_shell.project import Project


def save_project_bundle(
    project: Project,
    out_dir: Path | str,
    *,
    copy_image: bool = True,
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    img_src = Path(project.image_path)
    if copy_image and img_src.is_file():
        dest = out_dir / img_src.name
        if dest.resolve() != img_src.resolve():
            shutil.copy2(img_src, dest)
        project = project.model_copy(update={"image_path": str(dest)})
    json_path = out_dir / "project.json"
    project.save(json_path)
    return json_path
