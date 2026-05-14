"""Filter PAGE XML training data to TextLines that actually have transcribed text.

GT corpora often contain TextLines that were drawn (polygons) but never
transcribed (empty `<Unicode/>`). ``ketos train`` silently drops them, but
they still cost parse time and inflate the apparent corpus size — and they
hide skew in the GT (e.g., 50% of "lines" being un-transcribed).

This module rewrites each XML keeping only TextLines whose TextEquiv/Unicode
has non-empty text. Empty TextRegions are dropped too. The matching image is
copied alongside the filtered XML.
"""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _has_text(text_line: ET.Element) -> bool:
    for child in text_line.iter():
        if _local(child.tag) == "Unicode" and child.text and child.text.strip():
            return True
    return False


def filter_xml(src_xml: Path, dst_xml: Path) -> tuple[int, int]:
    """Filter one XML. Returns ``(lines_before, lines_after)``."""
    tree = ET.parse(str(src_xml))
    root = tree.getroot()
    ns_uri = ""
    if "}" in root.tag:
        ns_uri = root.tag.split("}")[0].lstrip("{")
        ET.register_namespace("", ns_uri)

    n_before = 0
    n_after = 0
    # Collect (parent, text_line) pairs that lack text
    to_remove: list[tuple[ET.Element, ET.Element]] = []
    parent_map = {child: parent for parent in root.iter() for child in parent}
    for el in list(root.iter()):
        if _local(el.tag) != "TextLine":
            continue
        n_before += 1
        if _has_text(el):
            n_after += 1
        else:
            parent = parent_map.get(el)
            if parent is not None:
                to_remove.append((parent, el))

    for parent, tl in to_remove:
        try:
            parent.remove(tl)
        except ValueError:
            pass

    # Drop now-empty TextRegions (no remaining TextLine children)
    region_removes: list[tuple[ET.Element, ET.Element]] = []
    parent_map = {child: parent for parent in root.iter() for child in parent}
    for el in list(root.iter()):
        if _local(el.tag) != "TextRegion":
            continue
        has_tl = any(_local(child.tag) == "TextLine" for child in el.iter())
        if not has_tl:
            parent = parent_map.get(el)
            if parent is not None:
                region_removes.append((parent, el))
    for parent, region in region_removes:
        try:
            parent.remove(region)
        except ValueError:
            pass

    dst_xml.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(dst_xml), xml_declaration=True, encoding="utf-8")
    return n_before, n_after


def filter_directory(
    src_dir: Path,
    dst_dir: Path,
    *,
    copy_images: bool = True,
) -> dict:
    """Filter every *.xml in src_dir, copy the matching image too.

    Returns a dict with totals + a list of per-file (stem, before, after).
    """
    src_dir = Path(src_dir)
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    image_exts = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
    rows: list[dict] = []
    total_before = total_after = 0
    n_kept_files = 0
    for xml in sorted(src_dir.glob("*.xml")):
        try:
            before, after = filter_xml(xml, dst_dir / xml.name)
        except ET.ParseError as e:
            rows.append({"stem": xml.stem, "before": 0, "after": 0, "error": str(e)})
            continue
        total_before += before
        total_after += after
        rows.append({"stem": xml.stem, "before": before, "after": after})
        if after == 0:
            # No lines with text — drop the empty XML so ketos doesn't waste cycles
            (dst_dir / xml.name).unlink(missing_ok=True)
            continue
        n_kept_files += 1
        if copy_images:
            for ext in image_exts:
                src_img = xml.with_suffix(ext)
                if src_img.is_file():
                    shutil.copy2(src_img, dst_dir / src_img.name)
                    break

    return {
        "n_files_in": len(rows),
        "n_files_kept": n_kept_files,
        "lines_before": total_before,
        "lines_after": total_after,
        "drop_ratio": (1.0 - total_after / total_before) if total_before else 0.0,
        "rows": rows,
    }
