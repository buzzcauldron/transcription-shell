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

from dendro_shell.detect.methods import method_payload
from dendro_shell.paths import default_library_dir, projects_dir
from dendro_shell.preprocess import list_presets, preprocess_pil
from dendro_shell.project import MeasurePath, Point, Project, RingTick, ScaleInfo
from dendro_shell.geometry import calibrate_scale, estimate_pith_center, polar_unwrap
from dendro_shell.pipeline import export_all, run_detect
from dendro_shell.series import (
    assign_years,
    build_width_series,
    drought_stress_series,
    skeleton_plot_values,
)
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
        active = get_active_checkpoint()
        payload = method_payload(active_unet=active.name if active else None)
        return {"ok": True, "version": "0.1.0", **payload}

    @app.get("/api/presets")
    def presets():
        return {"presets": list_presets()}

    @app.get("/api/methods")
    def methods():
        """Detection stack: classical → boolean bridge → U-Net."""
        active = get_active_checkpoint()
        return method_payload(active_unet=active.name if active else None)

    @app.get("/api/models")
    def models():
        active = get_active_checkpoint()
        payload = method_payload(active_unet=active.name if active else None)
        return {
            "models": list_models(),
            "active": active.name if active else None,
            **payload,
        }

    @app.post("/api/models/activate")
    def activate_model(payload: dict):
        set_active(payload["name"])
        return {"active": payload["name"]}

    def _open_and_detect(image_path: Path, *, outer_year: int | None = None) -> Project:
        """Open image and run stack default detect (boolean for discs)."""
        try:
            proj = run_detect(
                image_path,
                method="auto",
                preset="auto",
                sample_type="auto",
                outer_year=outer_year,
                sample_code=image_path.stem,
                auto=True,
            )
        except Exception as e:  # noqa: BLE001 — still open image for manual measure
            from dendro_shell.detect.classical import infer_sample_type
            from dendro_shell.project import MeasurePath

            img = Image.open(image_path).convert("RGB")
            st = infer_sample_type(img)
            proj = Project(
                image_path=str(image_path.resolve()),
                sample_code=image_path.stem,
                sample_type=st,  # type: ignore[arg-type]
                preprocess_preset="dark_disc" if st == "disc" else "sanded_core",
                detect_method="classical",
                outer_year=outer_year,
                notes=f"auto-detect failed: {e}",
                paths=[MeasurePath(id="path0")],
            )
        _set_project(proj)
        return proj

    @app.get("/api/project")
    def get_project():
        p = _project()
        if p is None and _STATE.get("open_image"):
            # Lazy open CLI-provided image and auto-detect
            img_path = Path(_STATE["open_image"]).resolve()
            if img_path.is_file():
                p = _open_and_detect(img_path)
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
        proj = _open_and_detect(dest)
        return {"project": proj.to_dict()}

    @app.post("/api/open-path")
    def open_path(payload: dict):
        path = Path(payload["path"]).expanduser().resolve()
        if not path.is_file():
            return JSONResponse({"error": f"Not found: {path}"}, status_code=404)
        proj = _open_and_detect(path, outer_year=payload.get("outer_year"))
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
        method = payload.get("method", p.detect_method) or "auto"
        preset = payload.get("preset") or p.preprocess_preset or "auto"
        # None → adaptive; only use explicit values when provided
        min_d = payload.get("min_distance_px")
        prom = payload.get("prominence")
        min_d = float(min_d) if min_d is not None else None
        prom = float(prom) if prom is not None else None

        # Rebuild transect unless user drew ≥2 points and asked to keep path
        keep_path = bool(payload.get("keep_path"))
        path_pts = None
        if keep_path and payload.get("path") and len(payload["path"]) >= 2:
            path_pts = [Point(**pt) for pt in payload["path"]]
        elif keep_path and p.paths and len(p.paths[0].points) >= 2:
            path_pts = p.paths[0].points

        pith = p.pith
        if payload.get("pith"):
            pith = Point(**payload["pith"])

        sample_type = payload.get("sample_type") or p.sample_type or "auto"
        try:
            project = run_detect(
                p.image_path,
                method=method,
                preset=preset,
                sample_type=sample_type,
                pith=pith,
                path_points=path_pts,
                angle_deg=float(payload.get("angle_deg", 0)),
                min_distance_px=min_d,
                prominence=prom,
                outer_year=payload.get("outer_year", p.outer_year),
                sample_code=p.sample_code,
                auto=True,
            )
        except (FileNotFoundError, RuntimeError, ValueError) as e:
            # Missing U-Net checkpoint / train extra / bad params → JSON, not 500
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:  # noqa: BLE001 — keep UI usable on detect faults
            return JSONResponse({"error": f"detect failed: {e}"}, status_code=400)
        # Preserve metadata / scale
        project = project.model_copy(
            update={
                "scale": p.scale,
                "species": p.species,
                "tags": p.tags,
                "notes": p.notes,
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
            return {"years": [], "widths_um": [], "skeleton": [], "drought": {}}
        s = build_width_series(p)
        drought = drought_stress_series(s.widths_um)
        return {
            "years": s.years,
            "widths_um": s.widths_um,
            "widths_px": s.widths_px,
            "flags": s.flags,
            "skeleton": drought["pointer"],
            "drought": drought,
            "outer_year": p.outer_year,
            "sample_code": s.sample_code,
        }

    @app.post("/api/years")
    def set_outer_year(payload: dict):
        """Re-label fold years from a known outer (bark) year inward."""
        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        if "outer_year" not in payload or payload["outer_year"] in (None, ""):
            return JSONResponse({"error": "outer_year required"}, status_code=400)
        oy = int(payload["outer_year"])
        if not p.paths:
            p = p.model_copy(update={"outer_year": oy})
            _set_project(p)
            return {"project": p.to_dict()}
        path0 = p.paths[0]
        labeled = assign_years(path0.rings, oy)
        # Also set pith_year from innermost labeled ring
        pith_year = None
        for r in sorted(labeled, key=lambda t: t.distance_px):
            if r.year is not None and r.flag != "false":
                pith_year = r.year
                break
        new_paths = [path0.model_copy(update={"rings": labeled})] + list(p.paths[1:])
        p = p.model_copy(update={"outer_year": oy, "pith_year": pith_year, "paths": new_paths})
        _set_project(p)
        return {"project": p.to_dict(), "outer_year": oy, "pith_year": pith_year}

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

    @app.post("/api/paint")
    def paint_stroke(payload: dict):
        """Paint or erase boundary mask strokes (hard-segment labeling)."""
        import cv2

        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        img = _load_image()
        w, h = img.size
        mask_path = Path(p.paint_mask) if p.paint_mask else Path(p.image_path).parent / "paint_mask.png"
        if mask_path.is_file():
            mask = np.asarray(Image.open(mask_path).convert("L"))
            if mask.shape[:2] != (h, w):
                mask = np.zeros((h, w), dtype=np.uint8)
        else:
            mask = np.zeros((h, w), dtype=np.uint8)
        mode = payload.get("mode", "paint")  # paint | erase
        radius = int(payload.get("radius", 3))
        value = 0 if mode == "erase" else 255
        for stroke in payload.get("strokes", []):
            pts = stroke.get("points") or []
            if len(pts) == 1:
                cv2.circle(mask, (int(pts[0]["x"]), int(pts[0]["y"])), radius, value, -1)
            elif len(pts) >= 2:
                arr = np.array([[int(pt["x"]), int(pt["y"])] for pt in pts], dtype=np.int32)
                cv2.polylines(mask, [arr], False, value, max(1, radius * 2), cv2.LINE_AA)
        mask_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(mask).save(mask_path)
        p = p.model_copy(update={"paint_mask": str(mask_path)})
        _set_project(p)
        return {"paint_mask": str(mask_path), "project": p.to_dict()}

    @app.get("/api/paint")
    def get_paint():
        p = _project()
        if p is None or not p.paint_mask:
            return JSONResponse({"error": "no paint mask"}, status_code=404)
        path = Path(p.paint_mask)
        if not path.is_file():
            return JSONResponse({"error": "missing file"}, status_code=404)
        return FileResponse(path, media_type="image/png")

    @app.post("/api/path/incline-pair")
    def incline_pair(payload: dict | None = None):
        """Duplicate primary path as path1 and link for incline correction."""
        p = _project()
        if p is None or not p.paths:
            return JSONResponse({"error": "no path"}, status_code=400)
        primary = p.paths[0]
        offset = float((payload or {}).get("offset_y", 12))
        partner_pts = [
            Point(x=pt.x, y=pt.y + offset) for pt in primary.points
        ]
        partner = MeasurePath(
            id="path1",
            points=partner_pts,
            rings=[r.model_copy() for r in primary.rings],
        )
        primary = primary.model_copy(update={"incline_partner_id": "path1"})
        paths = [primary, partner]
        # keep any other paths beyond the first two
        if len(p.paths) > 2:
            paths.extend(p.paths[2:])
        p = p.model_copy(update={"paths": paths})
        _set_project(p)
        return {"project": p.to_dict()}

    @app.get("/api/viz/breaks")
    def viz_breaks(preset: str = "dark_disc"):
        """Overlay break mask (red) + ring fragments (teal) for Boolean bridge."""
        import cv2

        from dendro_shell.detect.boolean_bridge import detect_break_mask, detect_ring_map
        from dendro_shell.preprocess import preprocess_gray
        from dendro_shell.viz import image_to_jpeg_bytes

        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        img = _load_image()
        gray = preprocess_gray(img, preset or p.preprocess_preset)
        pith = p.pith or estimate_pith_center(gray)
        breaks = detect_break_mask(gray, pith=pith)
        rings = detect_ring_map(gray)
        frags = cv2.bitwise_and(rings, cv2.bitwise_not(breaks))
        rgb = np.asarray(img.convert("RGB")).copy()
        red = rgb.copy()
        red[:, :, 0] = np.maximum(red[:, :, 0], breaks)
        teal = rgb.copy()
        teal[:, :, 1] = np.maximum(teal[:, :, 1], frags)
        teal[:, :, 2] = np.maximum(teal[:, :, 2], (frags * 0.7).astype(np.uint8))
        out = cv2.addWeighted(red, 0.55, teal, 0.45, 0)
        cv2.drawMarker(
            out,
            (int(pith.x), int(pith.y)),
            (212, 163, 92),
            markerType=cv2.MARKER_CROSS,
            markerSize=16,
            thickness=2,
        )
        return Response(image_to_jpeg_bytes(Image.fromarray(out)), media_type="image/jpeg")

    @app.get("/api/viz/skeleton")
    def viz_skeleton():
        from dendro_shell.viz import image_to_jpeg_bytes, render_skeleton_plot

        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        img = render_skeleton_plot(build_width_series(p))
        return Response(image_to_jpeg_bytes(img), media_type="image/jpeg")

    @app.get("/api/viz/growth")
    def viz_growth():
        from dendro_shell.viz import image_to_jpeg_bytes, render_growth_panel

        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        img = render_growth_panel(build_width_series(p))
        return Response(image_to_jpeg_bytes(img), media_type="image/jpeg")

    @app.get("/api/viz/tiles")
    def viz_tiles():
        from dendro_shell.viz import (
            extract_ring_tiles,
            image_to_jpeg_bytes,
            tiles_contact_sheet,
        )

        p = _project()
        if p is None or not p.paths:
            return JSONResponse({"error": "no path"}, status_code=400)
        tiles = extract_ring_tiles(_load_image(), p.paths[0])
        sheet = tiles_contact_sheet(tiles)
        return Response(image_to_jpeg_bytes(sheet, quality=88), media_type="image/jpeg")

    @app.post("/api/viz/compare")
    def viz_compare(payload: dict | None = None):
        """Run full detect stack (classical + boolean + unet) compare overlay."""
        from dendro_shell.detect.boolean_bridge import detect_rings_boolean_bridge
        from dendro_shell.detect.classical import detect_rings_along_path
        from dendro_shell.viz import image_to_jpeg_bytes, render_compare_overlay

        p = _project()
        if p is None or not p.paths or len(p.paths[0].points) < 2:
            return JSONResponse({"error": "need path with ≥2 points"}, status_code=400)
        payload = payload or {}
        preset = payload.get("preset", p.preprocess_preset)
        min_d = float(payload.get("min_distance_px", 12))
        prom = float(payload.get("prominence", 0.08))
        img = _load_image()
        path_pts = p.paths[0].points
        classical = detect_rings_along_path(
            img, path_pts, preset=preset, min_distance_px=min_d, prominence=prom
        )
        boolean_rings = []
        boolean_error = None
        try:
            pith = p.pith
            if pith is None and path_pts:
                mid = path_pts[len(path_pts) // 2]
                pith = Point(x=mid.x, y=mid.y)
            bres = detect_rings_boolean_bridge(img, path_pts, pith=pith, preset=preset)
            boolean_rings = bres.rings
        except Exception as e:  # noqa: BLE001 — surface in response
            boolean_error = str(e)
        unet_rings = []
        unet_error = None
        try:
            from dendro_shell.detect.unet import detect_rings_unet

            unet = detect_rings_unet(
                img, path_pts, preset=preset, min_distance_px=min_d, prominence=prom
            )
            unet_rings = unet.rings
        except Exception as e:  # noqa: BLE001 — surface in response
            unet_error = str(e)
        overlay = render_compare_overlay(
            img, classical.rings, unet_rings, p.paths[0], boolean_rings=boolean_rings
        )
        note_parts = []
        if boolean_error:
            note_parts.append(f"boolean:{boolean_error}")
        if unet_error:
            note_parts.append(f"unet:{unet_error}")
        return Response(
            image_to_jpeg_bytes(overlay),
            media_type="image/jpeg",
            headers={"X-Stack-Note": (" | ".join(note_parts))[:300]},
        )

    @app.get("/api/viz/report")
    def viz_report():
        from dendro_shell.viz import image_to_jpeg_bytes, render_report_png

        p = _project()
        if p is None:
            return JSONResponse({"error": "no project"}, status_code=400)
        return Response(image_to_jpeg_bytes(render_report_png(p)), media_type="image/jpeg")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico")
    def favicon():
        # Tiny inline SVG as ICO-substitute so browsers don't 404
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
            "<circle cx='16' cy='16' r='14' fill='none' stroke='#1f5c45' stroke-width='2'/>"
            "<circle cx='16' cy='16' r='8' fill='none' stroke='#152019' stroke-width='1.5'/>"
            "<circle cx='16' cy='16' r='2' fill='#b42318'/>"
            "</svg>"
        )
        return Response(svg, media_type="image/svg+xml")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app
