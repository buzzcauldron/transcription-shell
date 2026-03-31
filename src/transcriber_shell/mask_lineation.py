"""Mask tensor → PageXML lines file (latin_documents-style baselines).

Requires numpy + pillow. Optional: torch/opencv in user inference callable.
"""

from __future__ import annotations

import hashlib
import importlib
from html import escape as html_esc
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from transcriber_shell.config import Settings


class MaskLineationError(RuntimeError):
    pass


def _checksum_image(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _load_inference_callable(spec: str) -> Callable[..., Any]:
    if ":" not in spec:
        raise MaskLineationError(
            "mask_inference_callable must be 'module.submodule:function_name'"
        )
    mod_path, _, fn_name = spec.rpartition(":")
    mod_path = mod_path.strip()
    fn_name = fn_name.strip()
    if not mod_path or not fn_name:
        raise MaskLineationError("invalid mask_inference_callable")
    mod = importlib.import_module(mod_path)
    fn = getattr(mod, fn_name, None)
    if not callable(fn):
        raise MaskLineationError(f"{spec} is not callable")
    return fn


def _resolve_pred_npy_path(template: str, *, stem: str, job_id: str) -> Path:
    try:
        resolved = template.format(stem=stem, job_id=job_id)
    except KeyError as e:
        raise MaskLineationError(
            f"mask_pred_npy_path: unknown placeholder {e}; use {{stem}} or {{job_id}}"
        ) from e
    return Path(resolved).expanduser().resolve()


def _resolve_optional_template(template: str, *, stem: str, job_id: str) -> Path:
    try:
        resolved = template.format(stem=stem, job_id=job_id)
    except KeyError as e:
        raise MaskLineationError(
            f"path template: unknown placeholder {e}; use {{stem}} or {{job_id}}"
        ) from e
    return Path(resolved).expanduser().resolve()


def load_pred_masks(
    image_path: Path,
    job_id: str,
    settings: Settings,
) -> np.ndarray:
    """Return float or bool array of shape (num_lines, H, W).

    Plugins loaded via ``mask_inference_callable`` receive the same ``settings`` object;
    they may read ``settings.mask_device``, ``settings.mask_weights_path``, etc.
    """
    s = settings
    if s.mask_inference_callable:
        fn = _load_inference_callable(s.mask_inference_callable)
        pred = fn(image_path, s)
    elif s.mask_pred_npy_path:
        p = _resolve_pred_npy_path(s.mask_pred_npy_path, stem=image_path.stem, job_id=job_id)
        if not p.is_file():
            raise MaskLineationError(f"mask pred npy not found: {p}")
        pred = np.load(p, allow_pickle=False)
    else:
        raise MaskLineationError(
            "mask lineation requires TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE "
            "and/or TRANSCRIBER_SHELL_MASK_PRED_NPY_PATH (see docs/mask-lineation-plugin.md). "
            "For browser lineation without masks, set TRANSCRIBER_SHELL_LINEATION_BACKEND=glyph_machina "
            "(default) or kraken with TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH."
        )

    pred = np.asarray(pred)
    if pred.ndim == 2:
        pred = pred[np.newaxis, ...]
    if pred.ndim != 3:
        raise MaskLineationError(f"expected pred shape (L,H,W) or (H,W); got {pred.shape}")
    return pred


def _read_image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        w, h = im.size
    return int(w), int(h)


def _smooth_baseline_points(
    pts: list[tuple[int, int]], window: int
) -> list[tuple[int, int]]:
    if window <= 1 or len(pts) < 3:
        return pts
    w = min(window, len(pts))
    pad = w // 2
    xs = [p[0] for p in pts]
    ys = [float(p[1]) for p in pts]
    ypad = [ys[0]] * pad + ys + [ys[-1]] * pad
    out_y: list[int] = []
    for i in range(len(ys)):
        chunk = ypad[i : i + w]
        out_y.append(int(round(sum(chunk) / len(chunk))))
    return list(zip(xs, out_y))


def masks_to_baselines(
    pred: np.ndarray,
    img_w: int,
    img_h: int,
    *,
    threshold: float,
    smooth_window: int = 0,
) -> list[list[tuple[int, int]]]:
    """One baseline polyline per line (mask index), image pixel coordinates."""
    baselines: list[list[tuple[int, int]]] = []
    for i in range(pred.shape[0]):
        line_mask = pred[i]
        # Bicubic upsample probability map then threshold (smoother than nearest-neighbor masks)
        im = Image.fromarray((line_mask > threshold).astype(np.uint8) * 255)
        im_full = im.resize((img_w, img_h), Image.Resampling.BICUBIC)
        g = np.array(im_full, dtype=np.float64)
        arr = g > 127.0
        pts: list[tuple[int, int]] = []
        for x in range(img_w):
            ys = np.flatnonzero(arr[:, x])
            if ys.size:
                pts.append((x, int(np.median(ys))))
        if smooth_window > 1 and len(pts) >= 3:
            pts = _smooth_baseline_points(pts, smooth_window)
        if len(pts) > 500:
            step = len(pts) // 500 + 1
            pts = pts[::step]
        baselines.append(pts)
    return baselines


def build_mask_pagexml(
    *,
    image_filename: str,
    image_width: int,
    image_height: int,
    baselines: list[list[tuple[int, int]]],
    credit_url: str,
) -> str:
    PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
    safe_name = html_esc(image_filename, quote=False)
    safe_credit = html_esc(credit_url, quote=False)
    lines_xml: list[str] = []
    for i, pts in enumerate(baselines):
        if not pts:
            continue
        pts_s = " ".join(f"{x},{y}" for x, y in pts)
        safe_pts = html_esc(pts_s, quote=True)
        lines_xml.append(
            f'      <TextLine id="line_{i}"><Baseline points="{safe_pts}"/></TextLine>'
        )
    inner = "\n".join(lines_xml)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="{PAGE_NS}">
  <Metadata>
    <Creator>transcriber-shell mask lineation</Creator>
    <Comments>Credit: {safe_credit}</Comments>
  </Metadata>
  <Page imageFilename="{safe_name}" imageWidth="{image_width}" imageHeight="{image_height}">
    <TextRegion id="tr_0">
{inner}
    </TextRegion>
  </Page>
</PcGts>
"""


def masks_to_lines_xml(
    image_path: Path,
    pred: np.ndarray,
    output_path: Path,
    *,
    settings: Settings,
) -> None:
    image_path = image_path.expanduser().resolve()
    img_w, img_h = _read_image_size(image_path)
    baselines = masks_to_baselines(
        pred,
        img_w,
        img_h,
        threshold=settings.mask_threshold,
        smooth_window=max(0, int(settings.mask_baseline_smooth_window)),
    )
    if not any(baselines):
        raise MaskLineationError("no line masks produced non-empty baselines")
    xml = build_mask_pagexml(
        image_filename=image_path.name,
        image_width=img_w,
        image_height=img_h,
        baselines=baselines,
        credit_url=settings.lineation_credit_repo_url,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml, encoding="utf-8")


def fetch_lines_xml_mask(
    image_path: Path,
    job_id: str,
    settings: Settings | None = None,
) -> Path:
    """Run mask inference (or load npy), write ``artifacts_dir/job_id/lines.xml``."""
    s = settings or Settings()
    image_path = image_path.expanduser().resolve()
    if not image_path.is_file():
        raise MaskLineationError(f"image not found: {image_path}")

    out_dir = (s.artifacts_dir / job_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = out_dir / "source_image.sha256"
    meta.write_text(f"{_checksum_image(image_path)}  {image_path.name}\n", encoding="utf-8")

    pred = load_pred_masks(image_path, job_id, s)
    out_xml = out_dir / "lines.xml"
    masks_to_lines_xml(image_path, pred, out_xml, settings=s)
    if not out_xml.is_file() or out_xml.stat().st_size == 0:
        raise MaskLineationError("lines.xml missing or empty after mask lineation")

    if s.mask_reference_xml_path:
        ref_p = _resolve_optional_template(
            s.mask_reference_xml_path, stem=image_path.stem, job_id=job_id
        )
        if ref_p.is_file():
            from transcriber_shell.xml_tools.baseline_align import (
                apply_glyph_machina_corrections,
            )

            apply_glyph_machina_corrections(
                out_xml,
                ref_p,
                out_xml,
                centroid_match_px=s.mask_gm_centroid_match_px,
            )
    return out_xml
