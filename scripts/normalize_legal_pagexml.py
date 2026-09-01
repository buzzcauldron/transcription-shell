#!/usr/bin/env python3
"""Normalize legal GT PageXML to PRImA 2013-07-15 for ketos.

Handles:
  - nw-page-editor / eScriptorium namespace → PRImA
  - absolute imageFilename rewrite to sibling image on disk
  - skip unreadable XML

Usage:
  python scripts/normalize_legal_pagexml.py DIR [DIR ...]
  python scripts/normalize_legal_pagexml.py --in-place DIR
"""

from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

PRIMA_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".JPG", ".JPEG", ".PNG")

ET.register_namespace("", PRIMA_NS)


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _find_image(xml_path: Path, raw: str | None) -> Path | None:
    candidates: list[Path] = []
    if raw:
        p = Path(raw)
        candidates.append(p)
        candidates.append(xml_path.parent / p.name)
        if not p.is_absolute():
            candidates.append((xml_path.parent / p).resolve())
    for ext in IMAGE_EXTS:
        candidates.append(xml_path.with_suffix(ext))
    # case-insensitive stem match in sibling dir
    stem = xml_path.stem.lower()
    for p in xml_path.parent.iterdir():
        if p.is_file() and p.suffix in IMAGE_EXTS and p.stem.lower() == stem:
            candidates.append(p)
    for c in candidates:
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            continue
    return None


def normalize_xml(xml_path: Path, *, in_place: bool = True, out_dir: Path | None = None) -> Path | None:
    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, OSError):
        return None
    root = tree.getroot()

    # Rebuild under PRImA NS
    new_root = ET.Element(f"{{{PRIMA_NS}}}PcGts")
    # shallow-copy metadata if present
    for child in list(root):
        if _local(child.tag) == "Metadata":
            md = ET.SubElement(new_root, f"{{{PRIMA_NS}}}Metadata")
            for mchild in child:
                el = ET.SubElement(md, f"{{{PRIMA_NS}}}{_local(mchild.tag)}")
                el.text = mchild.text
            break

    page_old = None
    for el in root.iter():
        if _local(el.tag) == "Page":
            page_old = el
            break
    if page_old is None:
        return None

    img = _find_image(xml_path, page_old.get("imageFilename"))
    if img is None:
        return None

    page = ET.SubElement(
        new_root,
        f"{{{PRIMA_NS}}}Page",
        imageFilename=str(img),
        imageWidth=page_old.get("imageWidth") or "0",
        imageHeight=page_old.get("imageHeight") or "0",
    )
    # Prefer image dimensions from file when missing/zero
    try:
        from PIL import Image

        with Image.open(img) as im:
            w, h = im.size
        if page.get("imageWidth") in ("0", "", None):
            page.set("imageWidth", str(w))
        if page.get("imageHeight") in ("0", "", None):
            page.set("imageHeight", str(h))
    except Exception:
        pass

    n_lines = 0
    for region_old in page_old:
        if _local(region_old.tag) != "TextRegion":
            continue
        region = ET.SubElement(
            page,
            f"{{{PRIMA_NS}}}TextRegion",
            id=region_old.get("id") or f"r{n_lines}",
        )
        for sub in region_old:
            loc = _local(sub.tag)
            if loc == "Coords":
                ET.SubElement(region, f"{{{PRIMA_NS}}}Coords", points=sub.get("points") or "0,0 1,0 1,1 0,1")
            elif loc == "TextLine":
                text = ""
                coords = "0,0 1,0 1,1 0,1"
                baseline = None
                for tl_sub in sub:
                    tloc = _local(tl_sub.tag)
                    if tloc == "Coords":
                        coords = tl_sub.get("points") or coords
                    elif tloc == "Baseline":
                        baseline = tl_sub.get("points")
                    elif tloc == "TextEquiv":
                        for u in tl_sub.iter():
                            if _local(u.tag) == "Unicode" and u.text:
                                text = u.text
                                break
                if not (text or "").strip():
                    continue
                n_lines += 1
                tl = ET.SubElement(region, f"{{{PRIMA_NS}}}TextLine", id=sub.get("id") or f"l{n_lines}")
                ET.SubElement(tl, f"{{{PRIMA_NS}}}Coords", points=coords)
                if not baseline:
                    # synthesize from coords y-max * 0.85
                    ys = [int(float(p.split(",")[1])) for p in re.findall(r"[0-9.]+,[0-9.]+", coords)]
                    xs = [int(float(p.split(",")[0])) for p in re.findall(r"[0-9.]+,[0-9.]+", coords)]
                    if xs and ys:
                        yb = min(ys) + int(0.75 * (max(ys) - min(ys) or 1))
                        baseline = f"{min(xs)},{yb} {max(xs)},{yb}"
                    else:
                        baseline = "0,1 1,1"
                ET.SubElement(tl, f"{{{PRIMA_NS}}}Baseline", points=baseline)
                te = ET.SubElement(tl, f"{{{PRIMA_NS}}}TextEquiv")
                ET.SubElement(te, f"{{{PRIMA_NS}}}Unicode").text = text

    if n_lines == 0:
        return None

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / xml_path.name
    elif in_place:
        out_path = xml_path
    else:
        out_path = xml_path.with_name(xml_path.stem + ".prima.xml")

    ET.ElementTree(new_root).write(str(out_path), encoding="utf-8", xml_declaration=True)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dirs", nargs="+", type=Path)
    ap.add_argument("--in-place", action="store_true", default=True)
    ap.add_argument("--out-dir", type=Path, default=None, help="Write normalized XML here (disables in-place)")
    args = ap.parse_args()
    in_place = args.out_dir is None

    ok = fail = skip = 0
    for d in args.dirs:
        if not d.is_dir():
            print(f"[skip] not a dir: {d}")
            continue
        for xp in sorted(d.rglob("*.xml")):
            if xp.name.endswith(".prima.xml"):
                continue
            out = normalize_xml(xp, in_place=in_place, out_dir=args.out_dir)
            if out is None:
                fail += 1
            else:
                ok += 1
    print(f"normalized_ok={ok} failed_or_empty={fail}")


if __name__ == "__main__":
    main()
