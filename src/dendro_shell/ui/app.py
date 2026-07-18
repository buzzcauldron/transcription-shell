"""FastAPI application: measure routes + train API + static UI."""

from __future__ import annotations

import io
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from dendro_shell.paths import default_library_dir, projects_dir
from dendro_shell.preprocess import list_presets, preprocess_pil
from dendro_shell.project import MeasurePath, Point, Project, RingTick, ScaleInfo
from dendro_shell.geometry import calibrate_scale, estimate_pith_center, polar_unwrap
from dendro_shell.pipeline import export_all, run_detect
from dendro_shell.series import build_width_series, skeleton_plot_values
from dendro_shell.train.dataset import add_project_to_library, list_library_entries
from dendro_shell.train.job import TrainConfig, get_train_status, request_stop, run_training
from dendro_shell.train.registry import get_active_checkpoint, list_models, set_active
from dendro_shell.crossdate import correlate_against_reference


STATIC_DIR = Path(__file__).parent / "static"

# Session state for the single-user local app
_STATE: dict[str, Any] = {
    "project": None,
    "image_path": None,
    "library_dir": None,
    "open_image": None,
}


def create_app(open_image: str | None = None, library_dir: str | None = None):
    try:
        from fastapi import FastAPI, File, UploadFile
        from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as e:
        raise RuntimeError("pip install -e '.[ui]'") from e

    _STATE["library_dir"] = library_dir or str(default_library_dir())
    _STATE["open_image"] = open_image

    app = FastAPI(title="dendro-shell", version="0.1.0")

    def _project() -> Project | None:
        return _STATE.get("project")

    def _set_project(p: Project) -> None:
        _STATE["project"] = p
        _STATE["image_path"] = p.image_path

    def _load_image() -> Image.Image:
        path = _STATE.get("image_path")
        if not path:
            raise FileNotFoundError("No image loaded")
        return Image.open(path).convert("RGB")

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": "0.1.0"}

    @app.get("/api/presets")
    def presets():
        return {"presets": list_presets()}

    @app.get("/api/models")
    def models():
        active = get_active_checkpoint()
        return {
            "models": list_models(),
            "active": active.name if active else None,
            "methods": ["classical", "unet"],
        }

    @app.post("/api/models/activate")
    def activate_model(payload: dict):
        set_active(payload["name"])
        return {"active": payload["name"]}

    @app.get("/api/project")
    def get_project():
        p = _project()
        if p is None and _STATE.get("open_image"):
            # Lazy open CLI-provided image
            img_path = Path(_STATE["open_image"]).resolve()
            if img_path.is_file():
                proj = Project(
                    image_path=str(img_path),
                    sample_code=img_path.stem,
                )
                _set_project(proj)
                p = proj
                _STATE["open_image"] = None
        if p is None:
            return {"project": None}
        return {"project": p.to_dict()}

    @app.post("/api/project")
    def put_project(payload: dict):
        p = Project.model_validate(payload.get("project") or payload)
        _set_project(p)
        return {"project": p.to_dict()}

    @app.post("/api/open")
    async def open_upload(file: UploadFile = File(...)):
        data = await file.read()
        dest_dir = projects_dir() / uuid.uuid4().hex[:10]
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = file.filename or "sample.png"
        dest = dest_dir / Path(name).name
        dest.write_bytes(data)
        proj = Project(image_path=str(dest), sample_code=dest.stem)
        _set_project(proj)
        return {"project": proj.to_dict()}

    @app.post("/api/open-path")
    def open_path(payload: dict):
        path = Path(payload["path"]).expanduser().resolve()
        if not path.is_file():
            return JSONResponse({"error": f"Not found: {path}"}, status_code=404)
        proj = Project(image_path=str(path), sample_code=path.stem)
        _set_project(proj)
        return {"project": proj.to_dict()}

    @app.get("/api/image")
    def get_image(preset: str | None = None, max_side: int = 4096):
        """Serve measure image at native resolution (canvas scales for display)."""
        img = _load_image()
        if preset and preset != "none":
            img = preprocess_pil(img, preset).convert("RGB")
        w, h = img.size
        if max_side > 0 and max(w, h) > max_side:
            s = max_side / max(w, h)
            img = img.resize((int(w * s), int(h * s)), Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        return Response(
            buf.getvalue(),
            media_type="image/jpeg",
            headers={"X-Image-Width": str(w), "X-Image-Height": str(h)},
        )

    @app.get("/api/polar")
    def get_polar(preset: str = "sanded_core", n_angles: int = 360):
        p = _project()
        if p is None or p.pith is None:
            return JSONResponse({"error": "pith required"}, status_code=400)
        from dendro_shell.preprocess import preprocess_gray

        gray = preprocess_gray(_load_image(), preset)
        polar = polar_unwrap(gray, p.pith, n_angles=n_angles)
        # normalize to viewable
        polar_u8 = (
            (polar - polar.min()) / (polar.max() - polar.min() + 1e-8) * 255
        ).astype(np.uint8)
        img = Image.fromarray(polar_u8, mode="L").convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return Response(buf.getvalue(), media_type="image/jpeg")

    @app.post("/api/detect")
    def detect(payload: dict):
        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        method = payload.get("method", p.detect_method)
        preset = payload.get("preset", p.preprocess_preset)
        min_d = float(payload.get("min_distance_px", 8))
        prom = float(payload.get("prominence", 0.08))
        path_pts = None
        if payload.get("path"):
            path_pts = [Point(**pt) for pt in payload["path"]]
        elif p.paths and p.paths[0].points:
            path_pts = p.paths[0].points

        pith = p.pith
        if payload.get("pith"):
            pith = Point(**payload["pith"])

        project = run_detect(
            p.image_path,
            method=method,
            preset=preset,
            sample_type=payload.get("sample_type", p.sample_type),
            pith=pith,
            path_points=path_pts,
            angle_deg=float(payload.get("angle_deg", 0)),
            min_distance_px=min_d,
            prominence=prom,
            outer_year=payload.get("outer_year", p.outer_year),
            sample_code=p.sample_code,
        )
        # Preserve metadata / scale
        project = project.model_copy(
            update={
                "scale": p.scale,
                "species": p.species,
                "tags": p.tags,
                "notes": p.notes,
                "sample_type": payload.get("sample_type", p.sample_type),
            }
        )
        _set_project(project)
        return {"project": project.to_dict()}

    @app.post("/api/pith/estimate")
    def pith_estimate(payload: dict | None = None):
        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        from dendro_shell.preprocess import preprocess_gray

        preset = (payload or {}).get("preset", p.preprocess_preset)
        gray = preprocess_gray(_load_image(), preset)
        pith = estimate_pith_center(gray)
        p = p.model_copy(update={"pith": pith, "sample_type": "disc"})
        _set_project(p)
        return {"pith": pith.model_dump(), "project": p.to_dict()}

    @app.post("/api/scale")
    def set_scale(payload: dict):
        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        if "micrometers_per_pixel" in payload:
            scale = ScaleInfo(micrometers_per_pixel=float(payload["micrometers_per_pixel"]))
        else:
            scale = calibrate_scale(
                Point(**payload["p1"]),
                Point(**payload["p2"]),
                float(payload["known_length"]),
                payload.get("known_unit", "mm"),
            )
        p = p.model_copy(update={"scale": scale})
        _set_project(p)
        return {"scale": scale.model_dump(), "project": p.to_dict()}

    @app.get("/api/series")
    def series():
        p = _project()
        if p is None:
            return {"years": [], "widths_um": [], "skeleton": []}
        s = build_width_series(p)
        return {
            "years": s.years,
            "widths_um": s.widths_um,
            "widths_px": s.widths_px,
            "flags": s.flags,
            "skeleton": skeleton_plot_values(s.widths_um),
            "sample_code": s.sample_code,
        }

    @app.post("/api/export")
    def export(payload: dict | None = None):
        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        out = Path((payload or {}).get("out_dir") or (Path(p.image_path).parent / "dendro_out"))
        return export_all(p, out)

    @app.post("/api/library/add")
    def library_add(payload: dict | None = None):
        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        dest = add_project_to_library(
            p,
            _STATE["library_dir"],
            name=(payload or {}).get("name"),
        )
        return {"path": str(dest), "entries": list_library_entries(_STATE["library_dir"])}

    @app.get("/api/library")
    def library_list():
        return {
            "library_dir": _STATE["library_dir"],
            "entries": list_library_entries(_STATE["library_dir"]),
        }

    @app.post("/api/train/start")
    def train_start(payload: dict):
        cfg = TrainConfig(
            library_dir=payload.get("library_dir") or _STATE["library_dir"],
            name=payload.get("name", "boundary_unet"),
            epochs=int(payload.get("epochs", 30)),
            imgsz=int(payload.get("imgsz", 512)),
            batch_size=int(payload.get("batch_size", 2)),
            lr=float(payload.get("lr", 1e-3)),
            augment=bool(payload.get("augment", True)),
            device=payload.get("device", "auto"),
            species=payload.get("species"),
            tag=payload.get("tag"),
            fine_tune=bool(payload.get("fine_tune", True)),
            activate=bool(payload.get("activate", True)),
            overwrite=bool(payload.get("overwrite", True)),
        )
        try:
            st = run_training(cfg, background=True)
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return st.to_dict()

    @app.post("/api/train/stop")
    def train_stop():
        request_stop()
        return get_train_status().to_dict()

    @app.get("/api/train/status")
    def train_status():
        return get_train_status().to_dict()

    @app.post("/api/crossdate")
    def crossdate(payload: dict):
        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        series = build_width_series(p)
        hits = correlate_against_reference(
            series,
            payload["reference"],
            min_overlap=int(payload.get("min_overlap", 20)),
            max_lag=int(payload.get("max_lag", 20)),
        )
        return {
            "hits": [
                {
                    "lag": h.lag,
                    "correlation": h.correlation,
                    "overlap": h.overlap,
                    "reference_id": h.reference_id,
                }
                for h in hits[:15]
            ]
        }

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app
