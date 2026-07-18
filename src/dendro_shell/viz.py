"""Publication-leaning figures: skeleton plot, growth panel, compare overlay, tiles."""

from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from dendro_shell.geometry import point_at_distance, resample_path
from dendro_shell.project import MeasurePath, Project, RingTick
from dendro_shell.series import WidthSeries, build_width_series, skeleton_plot_values


# Resin / ash palette (matches UI)
_C_INK = (26, 34, 32)
_C_ACCENT = (212, 163, 92)
_C_TEAL = (111, 191, 163)
_C_CORAL = (224, 122, 95)
_C_BOOLEAN = (120, 170, 230)  # stack: boolean bridge
_C_MUTED = (154, 173, 163)
_C_PAPER = (232, 239, 233)


def _font(size: int = 14):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def render_skeleton_plot(
    series: WidthSeries,
    *,
    width: int = 900,
    height: int = 220,
) -> Image.Image:
    """Classic dendro skeleton: pointer years as stems below a baseline."""
    img = Image.new("RGB", (width, height), _C_INK)
    draw = ImageDraw.Draw(img)
    font = _font(12)
    title = f"Skeleton · {series.sample_code or 'series'}"
    draw.text((16, 10), title, fill=_C_PAPER, font=_font(16))

    if not series.years:
        draw.text((16, height // 2), "No series", fill=_C_MUTED, font=font)
        return img

    skel = skeleton_plot_values(series.widths_um)
    n = len(skel)
    pad_l, pad_r, pad_t, pad_b = 48, 24, 40, 36
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    baseline = pad_t + plot_h * 0.45
    draw.line([(pad_l, baseline), (width - pad_r, baseline)], fill=_C_MUTED, width=1)

    for i, (y, flag, s) in enumerate(zip(series.years, series.flags, skel)):
        x = pad_l + (i + 0.5) * plot_w / n
        if flag == "missing":
            draw.ellipse([x - 3, baseline - 3, x + 3, baseline + 3], outline=_C_MUTED)
            continue
        if s > 0:
            stem = plot_h * 0.35
            draw.line([(x, baseline), (x, baseline + stem)], fill=_C_ACCENT, width=2)
            draw.ellipse([x - 2.5, baseline + stem - 2.5, x + 2.5, baseline + stem + 2.5], fill=_C_ACCENT)
        else:
            draw.line([(x, baseline - 4), (x, baseline + 4)], fill=_C_TEAL, width=1)

    # Decade ticks
    for i, y in enumerate(series.years):
        if y % 10 == 0:
            x = pad_l + (i + 0.5) * plot_w / n
            draw.line([(x, pad_t + plot_h - 4), (x, pad_t + plot_h)], fill=_C_PAPER, width=1)
            draw.text((x - 12, pad_t + plot_h + 4), str(y), fill=_C_MUTED, font=font)
    return img


def render_growth_panel(
    series: WidthSeries,
    *,
    width: int = 900,
    height: int = 280,
) -> Image.Image:
    """Ring-width bars + mean line with missing gaps."""
    img = Image.new("RGB", (width, height), _C_INK)
    draw = ImageDraw.Draw(img)
    font = _font(12)
    draw.text((16, 10), f"Ring widths · {series.sample_code or 'series'}", fill=_C_PAPER, font=_font(16))
    if not series.widths_um:
        draw.text((16, height // 2), "No widths", fill=_C_MUTED, font=font)
        return img

    pad_l, pad_r, pad_t, pad_b = 48, 24, 40, 36
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    vals = list(series.widths_um)
    vmax = max(vals) or 1.0
    mean = float(np.mean([v for v in vals if v > 0])) if any(v > 0 for v in vals) else 0.0
    n = len(vals)
    bw = plot_w / n

    # mean line
    my = pad_t + plot_h - (mean / vmax) * plot_h
    draw.line([(pad_l, my), (width - pad_r, my)], fill=_C_ACCENT, width=1)

    for i, (v, flag, year) in enumerate(zip(vals, series.flags, series.years)):
        x0 = pad_l + i * bw
        if flag == "missing" or v <= 0:
            draw.rectangle(
                [x0 + 1, pad_t + plot_h - 6, x0 + bw - 1, pad_t + plot_h],
                fill=_C_MUTED,
            )
            continue
        h = (v / vmax) * plot_h
        color = _C_CORAL if v < mean else _C_TEAL
        draw.rectangle(
            [x0 + 1, pad_t + plot_h - h, x0 + bw - 1, pad_t + plot_h],
            fill=color,
        )
        if year % 10 == 0:
            draw.text((x0, pad_t + plot_h + 4), str(year), fill=_C_MUTED, font=font)
    draw.text((pad_l, pad_t - 2), f"mean {mean:.0f} µm", fill=_C_ACCENT, font=font)
    return img


def render_confidence_overlay(project: Project, image: Image.Image | None = None) -> Image.Image:
    """Path with ticks sized/colored by confidence; translucent connector wedges."""
    if image is None:
        image = Image.open(project.image_path).convert("RGB")
    else:
        image = image.convert("RGB")
    arr = np.asarray(image).copy()
    overlay = arr.copy()
    for mp in project.paths:
        pts = [(int(round(p.x)), int(round(p.y))) for p in mp.points]
        if len(pts) >= 2:
            cv2.polylines(overlay, [np.array(pts, dtype=np.int32)], False, (111, 191, 163), 3, cv2.LINE_AA)
        ordered = sorted(mp.rings, key=lambda r: r.distance_px, reverse=True)
        for r in ordered:
            if r.flag == "false":
                continue
            pt = point_at_distance(mp.points, r.distance_px)
            conf = float(np.clip(r.confidence, 0.05, 1.0))
            radius = int(round(3 + 7 * conf))
            if r.flag == "missing":
                color = (154, 173, 163)
            elif r.flag == "uncertain":
                color = (212, 163, 92)
            else:
                # coral → teal by confidence
                color = (
                    int(224 * (1 - conf) + 111 * conf),
                    int(122 * (1 - conf) + 191 * conf),
                    int(95 * (1 - conf) + 163 * conf),
                )
            cv2.circle(
                overlay,
                (int(round(pt.x)), int(round(pt.y))),
                radius,
                color,
                -1,
                cv2.LINE_AA,
            )
            if r.year is not None:
                cv2.putText(
                    overlay,
                    str(r.year),
                    (int(round(pt.x)) + 6, int(round(pt.y)) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    (232, 239, 233),
                    1,
                    cv2.LINE_AA,
                )
    if project.pith is not None:
        cv2.drawMarker(
            overlay,
            (int(round(project.pith.x)), int(round(project.pith.y))),
            _C_ACCENT,
            markerType=cv2.MARKER_CROSS,
            markerSize=18,
            thickness=2,
        )
    blended = cv2.addWeighted(overlay, 0.72, arr, 0.28, 0)
    return Image.fromarray(blended)


def render_compare_overlay(
    image: Image.Image | np.ndarray,
    classical_rings: list[RingTick],
    unet_rings: list[RingTick],
    path: MeasurePath,
    boolean_rings: list[RingTick] | None = None,
) -> Image.Image:
    """Stack compare: classical (coral), boolean (blue), U-Net (teal)."""
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            base = Image.fromarray(image, mode="L").convert("RGB")
        else:
            base = Image.fromarray(image).convert("RGB")
    else:
        base = image.convert("RGB")
    arr = np.asarray(base).copy()
    pts = path.points
    if len(pts) >= 2:
        poly = [(int(p.x), int(p.y)) for p in pts]
        cv2.polylines(arr, [np.array(poly, dtype=np.int32)], False, (200, 200, 200), 2, cv2.LINE_AA)

    def _draw(rings: list[RingTick], color: tuple[int, int, int], offset: int):
        for r in rings:
            if r.flag == "false":
                continue
            pt = point_at_distance(pts, r.distance_px)
            cv2.circle(arr, (int(pt.x) + offset, int(pt.y)), 5, color, -1, cv2.LINE_AA)

    boolean_rings = boolean_rings or []
    _draw(classical_rings, _C_CORAL, -4)
    _draw(boolean_rings, _C_BOOLEAN, 0)
    _draw(unet_rings, _C_TEAL, 4)

    # link nearest classical ↔ boolean / unet matches
    for cr in classical_rings:
        if cr.flag == "false":
            continue
        for other, xoff in ((boolean_rings, 0), (unet_rings, 4)):
            if not other:
                continue
            ur = min(other, key=lambda u: abs(u.distance_px - cr.distance_px))
            if abs(ur.distance_px - cr.distance_px) > 20:
                continue
            a = point_at_distance(pts, cr.distance_px)
            b = point_at_distance(pts, ur.distance_px)
            cv2.line(
                arr,
                (int(a.x) - 4, int(a.y)),
                (int(b.x) + xoff, int(b.y)),
                (212, 163, 92),
                1,
                cv2.LINE_AA,
            )

    # legend
    cv2.putText(arr, "classical", (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, _C_CORAL, 2, cv2.LINE_AA)
    cv2.putText(arr, "boolean", (12, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.55, _C_BOOLEAN, 2, cv2.LINE_AA)
    cv2.putText(arr, "unet", (12, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.55, _C_TEAL, 2, cv2.LINE_AA)
    return Image.fromarray(arr)


def extract_ring_tiles(
    image: Image.Image | np.ndarray,
    path: MeasurePath,
    *,
    tile: int = 96,
    half_width: int = 48,
    max_tiles: int = 40,
) -> list[dict]:
    """Zoom crops centered on each ring tick (comma_review-style strip)."""
    if isinstance(image, Image.Image):
        arr = np.asarray(image.convert("RGB"))
    else:
        arr = np.asarray(image)
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
    h, w = arr.shape[:2]
    ordered = sorted(
        [r for r in path.rings if r.flag != "false"],
        key=lambda r: r.distance_px,
        reverse=True,
    )[:max_tiles]
    sample = resample_path(path.points, step_px=1.0)
    out: list[dict] = []
    for r in ordered:
        pt = point_at_distance(path.points, r.distance_px)
        # orient crop along path tangent
        idx = int(np.argmin(np.abs(sample.distances - r.distance_px))) if len(sample.distances) else 0
        x0 = max(0, int(pt.x) - tile // 2)
        y0 = max(0, int(pt.y) - half_width)
        x1 = min(w, x0 + tile)
        y1 = min(h, y0 + 2 * half_width)
        crop = arr[y0:y1, x0:x1].copy()
        # mark center
        cx, cy = int(pt.x - x0), int(pt.y - y0)
        if 0 <= cy < crop.shape[0] and 0 <= cx < crop.shape[1]:
            cv2.drawMarker(crop, (cx, cy), _C_ACCENT, markerType=cv2.MARKER_CROSS, markerSize=12, thickness=1)
        out.append(
            {
                "year": r.year,
                "distance_px": r.distance_px,
                "confidence": r.confidence,
                "flag": r.flag,
                "image": Image.fromarray(crop),
            }
        )
    return out


def tiles_contact_sheet(tiles: list[dict], *, cols: int = 8, pad: int = 4) -> Image.Image:
    if not tiles:
        return Image.new("RGB", (320, 80), _C_INK)
    tw = max(t["image"].size[0] for t in tiles)
    th = max(t["image"].size[1] for t in tiles)
    cols = min(cols, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + 22) + pad), _C_INK)
    draw = ImageDraw.Draw(sheet)
    font = _font(11)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        x = pad + c * (tw + pad)
        y = pad + r * (th + 22)
        sheet.paste(t["image"].resize((tw, th)), (x, y))
        label = str(t["year"] if t["year"] is not None else f'{t["distance_px"]:.0f}px')
        if t["flag"] == "missing":
            label += " · miss"
        draw.text((x, y + th + 2), label, fill=_C_ACCENT if t["flag"] == "ok" else _C_MUTED, font=font)
    return sheet


def render_report_png(project: Project, out_path: Path | str | None = None) -> Image.Image:
    """Stack confidence overlay + growth + skeleton into one tall figure."""
    series = build_width_series(project)
    overlay = render_confidence_overlay(project)
    # scale overlay to 900 wide
    ow = 900
    oh = int(overlay.height * (ow / overlay.width))
    overlay = overlay.resize((ow, oh), Image.BILINEAR)
    growth = render_growth_panel(series, width=ow)
    skel = render_skeleton_plot(series, width=ow)
    gap = 12
    total_h = oh + growth.height + skel.height + gap * 2
    canvas = Image.new("RGB", (ow, total_h), _C_INK)
    y = 0
    canvas.paste(overlay, (0, y))
    y += oh + gap
    canvas.paste(growth, (0, y))
    y += growth.height + gap
    canvas.paste(skel, (0, y))
    if out_path:
        canvas.save(out_path)
    return canvas


def image_to_jpeg_bytes(img: Image.Image, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
