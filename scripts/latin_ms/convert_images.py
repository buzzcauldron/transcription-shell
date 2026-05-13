#!/usr/bin/env python3
"""
convert_images.py — Convert any image format to pipeline-compatible JPEG/PNG.

Converts TIF/TIFF/BMP/WebP/GIF/PCX/PPM → JPEG by default.
JPEG and PNG inputs are copied or optionally rescaled in-place.

Usage:
    python3 convert_images.py <src> [<src2> ...] [options]

    python3 convert_images.py 00_sources/ --out-dir 01_pages/
    python3 convert_images.py *.tif --out-dir out/ --format png
    python3 convert_images.py image.tiff                  # writes image.jpg next to source

Options:
    --out-dir DIR       output directory (default: same as each source file)
    --format jpeg|png   output format (default: jpeg)
    --max-width PX      resize so width <= PX (default: 3000)
    --max-height PX     resize so height <= PX (no default; aspect-ratio respected)
    --quality N         JPEG quality 1-95 (default: 90)
    --keep-original     do not convert files that are already the target format
    --force             overwrite existing outputs
    --dry-run           print what would happen, do nothing
    --recurse           recurse into subdirectories of src
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is not installed. Run: pip install Pillow", file=sys.stderr)
    sys.exit(1)

CONVERTIBLE = {".tif", ".tiff", ".bmp", ".webp", ".gif", ".pcx", ".ppm", ".pgm", ".pbm", ".ico"}
PASSTHROUGH = {".jpg", ".jpeg", ".png"}


def find_images(sources: list[Path], recurse: bool) -> list[Path]:
    images = []
    all_ext = CONVERTIBLE | PASSTHROUGH
    for src in sources:
        if src.is_dir():
            pattern = "**/*" if recurse else "*"
            for p in sorted(src.glob(pattern)):
                if p.is_file() and p.suffix.lower() in all_ext:
                    images.append(p)
        elif src.is_file():
            images.append(src)
        else:
            print(f"  WARNING: {src} not found, skipping", file=sys.stderr)
    return images


def target_path(src: Path, out_dir: Path | None, fmt: str) -> Path:
    ext = ".jpg" if fmt == "jpeg" else ".png"
    name = src.stem + ext
    base = out_dir if out_dir else src.parent
    return base / name


def resize(img: Image.Image, max_width: int | None, max_height: int | None) -> Image.Image:
    w, h = img.size
    if max_width and w > max_width:
        ratio = max_width / w
        w, h = max_width, int(h * ratio)
    if max_height and h > max_height:
        ratio = max_height / h
        w, h = int(w * ratio), max_height
    if (w, h) != img.size:
        return img.resize((w, h), Image.LANCZOS)
    return img


def _scale_points(points_str: str, sx: float, sy: float) -> str:
    out = []
    for tok in points_str.split():
        if "," not in tok:
            out.append(tok)
            continue
        x, y = tok.split(",", 1)
        out.append(f"{round(float(x) * sx)},{round(float(y) * sy)}")
    return " ".join(out)


def scale_paired_xml(
    src_img: Path,
    dst_img: Path,
    orig_w: int,
    orig_h: int,
    new_w: int,
    new_h: int,
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

    # Preserve original namespace declaration
    ns_match = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    if ns_match:
        ET.register_namespace("", ns_match)
    tree.write(str(xml_dst), xml_declaration=True, encoding="unicode")
    return True


def convert_file(
    src: Path,
    out_dir: Path | None,
    fmt: str,
    max_width: int | None,
    max_height: int | None,
    quality: int,
    keep_original: bool,
    force: bool,
    dry_run: bool,
    scale_xml: bool = True,
) -> tuple[str, str]:
    """Return (status, message). Status: converted | skipped | error."""
    src_ext = src.suffix.lower()
    is_passthrough = src_ext in PASSTHROUGH
    target_ext = ".jpg" if fmt == "jpeg" else ".png"

    if is_passthrough and keep_original and src_ext == target_ext:
        return "skipped", f"{src.name} (already {fmt})"

    dst = target_path(src, out_dir, fmt)

    if dst.exists() and not force and not (is_passthrough and src == dst):
        return "skipped", f"{src.name} → {dst} (exists, use --force)"

    if dry_run:
        w, h = Image.open(src).size
        new_w, new_h = w, h
        if max_width and new_w > max_width:
            ratio = max_width / new_w
            new_w, new_h = max_width, int(new_h * ratio)
        if max_height and new_h > max_height:
            ratio = max_height / new_h
            new_w, new_h = int(new_w * ratio), max_height
        return "dry-run", f"{src.name} ({w}×{h}) → {dst.name} ({new_w}×{new_h})"

    try:
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)

        img = Image.open(src)

        # Flatten alpha for JPEG
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
        img = resize(img, max_width, max_height)

        save_kwargs: dict = {}
        if fmt == "jpeg":
            save_kwargs = {"quality": quality, "optimize": True}
        elif fmt == "png":
            save_kwargs = {"optimize": True}

        img.save(dst, format=fmt.upper(), **save_kwargs)

        xml_note = ""
        if scale_xml and img.size != orig_size:
            wrote = scale_paired_xml(src, dst, orig_size[0], orig_size[1], img.size[0], img.size[1], force)
            if wrote:
                xml_note = " + XML scaled"

        size_kb = dst.stat().st_size // 1024
        resize_note = f" → resized {orig_size[0]}×{orig_size[1]} to {img.size[0]}×{img.size[1]}" if img.size != orig_size else ""
        return "converted", f"{src.name}{resize_note} → {dst.name} ({size_kb} KB){xml_note}"

    except Exception as exc:
        return "error", f"{src.name}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert images to pipeline-compatible JPEG/PNG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sources", nargs="+", type=Path, help="files or directories to convert")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--format", choices=["jpeg", "png"], default="jpeg")
    parser.add_argument("--max-width", type=int, default=3000)
    parser.add_argument("--max-height", type=int, default=None)
    parser.add_argument("--quality", type=int, default=90)
    parser.add_argument("--keep-original", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--recurse", action="store_true")
    parser.add_argument("--no-scale-xml", action="store_true",
                        help="skip automatic PAGE XML coordinate scaling when image is resized")
    args = parser.parse_args()

    images = find_images(args.sources, args.recurse)
    if not images:
        print("No images found.", file=sys.stderr)
        return 1

    print(f"==> convert_images: {len(images)} image(s) → {args.format.upper()}"
          f"  max-width={args.max_width}  quality={args.quality}"
          + ("  [DRY RUN]" if args.dry_run else ""))

    counts = {"converted": 0, "skipped": 0, "error": 0, "dry-run": 0}
    for src in images:
        status, msg = convert_file(
            src=src,
            out_dir=args.out_dir,
            fmt=args.format,
            max_width=args.max_width,
            max_height=args.max_height,
            quality=args.quality,
            keep_original=args.keep_original,
            force=args.force,
            dry_run=args.dry_run,
            scale_xml=not args.no_scale_xml,
        )
        counts[status] = counts.get(status, 0) + 1
        prefix = {"converted": "  ✓", "skipped": "  –", "error": "  ✗", "dry-run": "  ?"}[status]
        print(f"{prefix} {msg}")

    verb = "Would convert" if args.dry_run else "Converted"
    key = "dry-run" if args.dry_run else "converted"
    print(f"\n  {verb} {counts[key]}, skipped {counts['skipped']}, errors {counts['error']}")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
