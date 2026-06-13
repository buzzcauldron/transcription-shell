"""Shared PageXML TextLine parsing for line-crop HTR backends."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


def _xml_namespace(element: ET.Element) -> str:
    m = re.match(r"\{.*\}", element.tag)
    return m.group(0)[1:-1] if m else ""


def parse_points(s: str) -> list[tuple[int, int]]:
    """PageXML points attribute: 'x1,y1 x2,y2 ...' → list of (x,y)."""
    pts: list[tuple[int, int]] = []
    for tok in (s or "").split():
        if "," not in tok:
            continue
        x_s, y_s = tok.split(",", 1)
        try:
            pts.append((int(float(x_s)), int(float(y_s))))
        except ValueError:
            continue
    return pts


@dataclass(frozen=True)
class TextLineRecord:
    bbox: tuple[int, int, int, int]  # x0, y0, x1, y1
    text: str
    line_id: str | None = None


def iter_text_lines(lines_xml_path: Path) -> list[TextLineRecord]:
    """Return TextLine bboxes and Unicode GT in document order."""
    tree = ET.parse(str(lines_xml_path))
    root = tree.getroot()
    ns_uri = _xml_namespace(root)
    ns = {"ns": ns_uri} if ns_uri else {}
    tag = lambda name: f"ns:{name}" if ns_uri else name

    records: list[TextLineRecord] = []
    for line in root.findall(f".//{tag('TextLine')}", ns):
        if line.get("custom") == "type {type:margin;}":
            continue
        coords = line.find(tag("Coords"), ns)
        if coords is None or not coords.get("points"):
            continue
        pts = parse_points(coords.get("points", ""))
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        bbox = (min(xs), min(ys), max(xs), max(ys))

        text = ""
        for te in line.findall(f".//{tag('TextEquiv')}", ns):
            uni = te.find(tag("Unicode"), ns)
            if uni is not None and uni.text:
                text = uni.text.strip()
                break

        records.append(
            TextLineRecord(bbox=bbox, text=text, line_id=line.get("id"))
        )
    return records


def line_bboxes(lines_xml_path: Path) -> list[tuple[int, int, int, int]]:
    return [r.bbox for r in iter_text_lines(lines_xml_path)]
