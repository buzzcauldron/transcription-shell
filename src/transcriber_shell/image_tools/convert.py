"""Image conversion and PAGE XML coordinate scaling.

The canonical logic; scripts/latin_ms/convert_images.py delegates here.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from PIL import Image

CONVERTIBLE = frozenset({".tif", ".tiff", ".bmp", ".webp", ".gif", ".pcx", ".ppm", ".pgm", ".pbm", ".ico"})
PASSTHROUGH = frozenset({".jpg", ".jpeg", ".png"})
ALL_IMAGE_EXTS = CONVERTIBLE | PASSTHROUGH

OutputFormat = Literal["jpeg", "png"]


def find_images(sources: list[Path], *, recurse: bool = False) -> list[Path]:
    images: list[Path] = []
    for src in sources:
        if src.is_dir():
            pattern = "**/*" if recurse else "*"
            for p in sorted(src.glob(pattern)):
                if p.is_file() and p.suffix.lower() in ALL_IMAGE_EXTS:
                    images.append(p)
        elif src.is_file():
            images.append(src)
    return images


def _scale_points(points_str: str, sx: float, sy: float) -> str:
    out: list[str] = []
    for tok in points_str.split():
        if "," not in tok:
            out.append(tok)
            continue
        x, _, y = tok.partition(",")
        out.append(f"{round(float(x) * sx)},{round(float(y) * sy)}")
    return " ".join(out)


def scale_paired_xml(
    src_img: Path,
    dst_img: Path,
    orig_w: int,
    orig_h: int,
    new_w: int,
    new_h: int,
    *,
    force: bool = False,
) -> bool:
    """Scale PAGE XML coords to match a resized image. Returns True if written."""
    xml_src = src_img.with_suffix(".xml")
    if not xml_src.exists():
        return False
    xml_dst = dst_img.with_suffix(".xml")
    if xml_dst.exists() and not force:
        return False

    sx = new_w / orig_w
    sy = new_h / orig_h
    tree = ET.parse(str(xml_src))
    root = tree.getroot()

    page = root.find(".//{*}Page")
    if page is not None:
        page.set("imageWidth", str(new_w))
        page.set("imageHeight", str(new_h))
        page.set("imageFilename", str(dst_img))

    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag in ("Coords", "Baseline"):
            pts = el.get("points", "")
            if pts:
                el.set("points", _scale_points(pts, sx, sy))

    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    if ns:
        ET.register_namespace("", ns)
    tree.write(str(xml_dst), xml_declaration=True, encoding="unicode")
    return True


def _target_path(src: Path, out_dir: Path | None, fmt: OutputFormat) -> Path:
    ext = ".jpg" if fmt == "jpeg" else ".png"
    base = out_dir if out_dir else src.parent
    return base / (src.stem + ext)


def _resize(img: Image.Image, max_width: int | None, max_height: int | None) -> Image.Image:
    w, h = img.size
    if max_width and w > max_width:
        h = int(h * max_width / w)
        w = max_width
    if max_height and h > max_height:
        w = int(w * max_height / h)
        h = max_height
    if (w, h) != img.size:
        return img.resize((w, h), Image.LANCZOS)
    return img


def convert_file(
    src: Path,
    *,
    out_dir: Path | None = None,
    fmt: OutputFormat = "jpeg",
    max_width: int | None = 3000,
    max_height: int | None = None,
    quality: int = 90,
    keep_original: bool = False,
    force: bool = False,
    dry_run: bool = False,
    scale_xml: bool = True,
) -> tuple[str, str]:
    """Convert one image. Returns (status, message). Status: converted | skipped | error."""
    src_ext = src.suffix.lower()
    is_passthrough = src_ext in PASSTHROUGH
    target_ext = ".jpg" if fmt == "jpeg" else ".png"

    if is_passthrough and keep_original and src_ext == target_ext:
        return "skipped", f"{src.name} (already {fmt})"

    dst = _target_path(src, out_dir, fmt)
    if dst.exists() and not force and not (is_passthrough and src == dst):
        return "skipped", f"{src.name} → {dst} (exists)"

    if dry_run:
        return "dry-run", f"{src.name} → {dst.name}"

    try:
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)

        img = Image.open(src)

        if fmt == "jpeg" and img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            if img.mode in ("RGBA", "LA"):
                bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode not in ("RGB", "L") and fmt == "jpeg":
            img = img.convert("RGB")

        orig_size = img.size
        img = _resize(img, max_width, max_height)

        save_kwargs: dict = {}
        if fmt == "jpeg":
            save_kwargs = {"quality": quality, "optimize": True}
        elif fmt == "png":
            save_kwargs = {"optimize": True}

        img.save(dst, format=fmt.upper(), **save_kwargs)

        xml_note = ""
        if scale_xml and img.size != orig_size:
            if scale_paired_xml(src, dst, orig_size[0], orig_size[1], img.size[0], img.size[1], force=force):
                xml_note = " + XML scaled"

        size_kb = dst.stat().st_size // 1024
        resize_note = (
            f" → resized {orig_size[0]}×{orig_size[1]} to {img.size[0]}×{img.size[1]}"
            if img.size != orig_size else ""
        )
        return "converted", f"{src.name}{resize_note} → {dst.name} ({size_kb} KB){xml_note}"

    except Exception as exc:
        return "error", f"{src.name}: {exc}"
