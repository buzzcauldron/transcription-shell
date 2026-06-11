"""Shared helpers: line-strip PNG + .gt.txt → minimal PAGE-XML for ketos -f page."""

from __future__ import annotations

import html
from pathlib import Path

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff")


def find_image_for_xml(xml_path: Path) -> Path | None:
    stem = xml_path.stem
    parent = xml_path.parent
    for ext in IMAGE_EXTS:
        candidate = parent / (stem + ext)
        if candidate.is_file():
            return candidate.resolve()
    return None


def find_gt_for_image(img_path: Path) -> Path | None:
    gt = img_path.with_suffix(".gt.txt")
    return gt if gt.is_file() else None


def write_line_strip_pagexml(img_path: Path, text: str, xml_path: Path | None = None) -> Path:
    """Write PAGE-XML for a single line-strip image. Returns xml path."""
    from PIL import Image

    img_path = img_path.resolve()
    out = (xml_path or img_path.with_suffix(".xml")).resolve()
    w, h = Image.open(img_path).size
    x1, y1, x2, y2 = 1, 1, max(w - 1, 1), max(h - 1, 1)
    bl = max(min(int(h * 0.8), h - 2), 1)
    pts = f"{x1},{y1} {x2},{y1} {x2},{y2} {x1},{y2}"
    ap = html.escape(str(img_path), quote=True)
    txt = html.escape(text.strip(), quote=False)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">\n'
        f'  <Page imageFilename="{ap}" imageWidth="{w}" imageHeight="{h}">\n'
        f'    <TextRegion id="r1"><Coords points="{pts}"/>\n'
        f'      <TextLine id="l1">\n'
        f'        <Coords points="{pts}"/>\n'
        f'        <Baseline points="{x1},{bl} {x2},{bl}"/>\n'
        f'        <TextEquiv><Unicode>{txt}</Unicode></TextEquiv>\n'
        f'      </TextLine>\n'
        f'    </TextRegion>\n'
        f'  </Page>\n'
        f'</PcGts>\n'
    )
    out.write_text(xml, encoding="utf-8")
    return out


def convert_png_gt_pair(img_path: Path, *, overwrite: bool = False) -> str:
    """Return 'ok', 'skip', or 'error'."""
    img_path = img_path.resolve()
    gt = find_gt_for_image(img_path)
    if gt is None:
        return "skip"
    xml_path = img_path.with_suffix(".xml")
    if xml_path.exists() and not overwrite:
        return "skip"
    try:
        text = gt.read_text(encoding="utf-8").strip()
    except OSError:
        return "error"
    if not text:
        return "skip"
    try:
        write_line_strip_pagexml(img_path, text, xml_path)
    except OSError:
        return "error"
    return "ok"
