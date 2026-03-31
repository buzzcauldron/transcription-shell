"""Validate human PAGE ground truth: dimensions vs image, non-empty baselines."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from transcriber_shell.xml_tools.lines_compare import extract_textline_baselines


def _local_name(el: ET.Element) -> str:
    tag = el.tag
    if tag.startswith("{"):
        return tag.split("}", 1)[-1]
    return tag


def _page_wh(root: ET.Element) -> tuple[int | None, int | None]:
    for el in root.iter():
        if _local_name(el) == "Page":
            iw = el.get("imageWidth")
            ih = el.get("imageHeight")
            try:
                w = int(iw) if iw is not None and str(iw).strip() else None
            except ValueError:
                w = None
            try:
                h = int(ih) if ih is not None and str(ih).strip() else None
            except ValueError:
                h = None
            return w, h
    return None, None


def validate_gt_pagexml(
    xml_path: str | Path,
    image_path: str | Path,
) -> tuple[bool, list[str]]:
    """Return (ok, messages). ``ok`` is False if any error-level check fails.

    Checks: XML parses; ``Page@imageWidth`` / ``imageHeight`` match ``image_path``;
    at least one ``TextLine`` with non-empty ``Baseline@points``.
    """
    xml_path = Path(xml_path)
    image_path = Path(image_path)
    msgs: list[str] = []

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        return False, [f"XML parse error: {e}"]
    except OSError as e:
        return False, [f"could not read XML: {e}"]

    root = tree.getroot()
    pw, ph = _page_wh(root)
    if pw is None or ph is None:
        msgs.append(
            "error: Page@imageWidth / imageHeight missing or invalid (needed for GT checks)"
        )
        return False, msgs

    try:
        from PIL import Image
    except ImportError:
        return False, ["Pillow required: pip install pillow"]

    try:
        with Image.open(image_path) as im:
            iw, ih = im.size
    except OSError as e:
        return False, [f"could not read image: {e}"]

    if (iw, ih) != (pw, ph):
        msgs.append(
            f"error: image size ({iw}x{ih}) != Page dimensions ({pw}x{ph}) in {xml_path.name}"
        )
        return False, msgs

    polys = extract_textline_baselines(xml_path)
    if not polys:
        msgs.append("error: no TextLine baselines with valid points")
        return False, msgs

    msgs.append(f"ok: {len(polys)} lines, dimensions {pw}x{ph} match image")
    return True, msgs


def cli_main() -> int:
    import argparse
    import sys

    p = argparse.ArgumentParser(
        description="Validate PAGE XML ground truth against image dimensions and baselines."
    )
    p.add_argument("xml", type=Path, help="PAGE XML file")
    p.add_argument("image", type=Path, help="Matching image (png/jpg/tiff)")
    args = p.parse_args()
    ok, lines = validate_gt_pagexml(args.xml, args.image)
    for line in lines:
        if line.startswith("error:"):
            print(line, file=sys.stderr)
        else:
            print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(cli_main())
