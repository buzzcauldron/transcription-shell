"""Scale vatlib GT images + XML coordinates so longest dimension ≤ MAX_PX.

Creates a new directory with rescaled JPEGs and updated PageXML files.
Images already within the limit are hard-linked (not copied) to save space.

Usage:
    python scale_vatlib_gt.py \
        --src /home/sethj/kraken-vatlib-gt \
        --dst /home/sethj/kraken-vatlib-gt-scaled \
        --max-px 1800
"""

from __future__ import annotations

import argparse
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image


def _scale_factor(w: int, h: int, max_px: int) -> float:
    longest = max(w, h)
    return min(1.0, max_px / longest)


def _scale_points(points_str: str, sx: float, sy: float) -> str:
    out = []
    for tok in points_str.split():
        if "," not in tok:
            out.append(tok)
            continue
        x, y = tok.split(",", 1)
        out.append(f"{round(float(x)*sx)},{round(float(y)*sy)}")
    return " ".join(out)


def process_pair(xml_src: Path, dst_dir: Path, max_px: int) -> None:
    tree = ET.parse(str(xml_src))
    root = tree.getroot()

    # Detect namespace
    import re
    m = re.match(r"\{.*\}", root.tag)
    ns_uri = m.group(0)[1:-1] if m else ""
    ns = {"ns": ns_uri}
    ET.register_namespace("", ns_uri)

    page = root.find(".//ns:Page", ns)
    if page is None:
        return

    img_src = Path(page.get("imageFilename", ""))
    if not img_src.is_file():
        # Try relative to XML dir
        img_src = xml_src.parent / img_src.name
    if not img_src.is_file():
        print(f"  SKIP (image not found): {xml_src.name}")
        return

    orig_w = int(page.get("imageWidth", 0))
    orig_h = int(page.get("imageHeight", 0))
    sf = _scale_factor(orig_w, orig_h, max_px)

    dst_img = dst_dir / img_src.name
    dst_xml = dst_dir / xml_src.name

    if sf >= 1.0:
        # Image within limits — hard-link if possible, otherwise copy
        if not dst_img.exists():
            try:
                os.link(img_src, dst_img)
            except OSError:
                import shutil
                shutil.copy2(img_src, dst_img)
        # Write XML with updated imageFilename pointing to dst
        page.set("imageFilename", str(dst_img))
        tree.write(str(dst_xml), xml_declaration=True, encoding="utf-8")
        return

    new_w = round(orig_w * sf)
    new_h = round(orig_h * sf)
    sx = new_w / orig_w
    sy = new_h / orig_h

    # Scale image
    if not dst_img.exists():
        with Image.open(img_src) as im:
            im_scaled = im.resize((new_w, new_h), Image.LANCZOS)
            im_scaled.save(dst_img, quality=90)

    # Scale all coord/baseline points in XML
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag in ("Baseline", "Coords"):
            pts = el.get("points", "")
            if pts:
                el.set("points", _scale_points(pts, sx, sy))

    page.set("imageFilename", str(dst_img))
    page.set("imageWidth", str(new_w))
    page.set("imageHeight", str(new_h))
    tree.write(str(dst_xml), xml_declaration=True, encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src", type=Path, required=True, help="Source GT directory")
    p.add_argument("--dst", type=Path, required=True, help="Destination directory")
    p.add_argument("--max-px", type=int, default=1800, help="Max longest dimension in pixels [default: 1800]")
    args = p.parse_args()

    args.dst.mkdir(parents=True, exist_ok=True)
    xmls = sorted(args.src.glob("*.xml"))
    print(f"Processing {len(xmls)} XMLs from {args.src} → {args.dst} (max {args.max_px}px)")
    scaled = skipped = 0
    for xml_path in xmls:
        process_pair(xml_path, args.dst, args.max_px)
        # Determine if it was scaled
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
        page = root.find(".//{*}Page")
        if page is not None:
            w = int(page.get("imageWidth", 0))
            h = int(page.get("imageHeight", 0))
            if max(w, h) > args.max_px:
                scaled += 1
            else:
                skipped += 1
    print(f"Done. Scaled: {scaled}, unchanged: {skipped}")


if __name__ == "__main__":
    main()
