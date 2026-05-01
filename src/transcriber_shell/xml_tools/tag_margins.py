"""Post-process PageXML: tag TextLine elements by layout role.

All lines start with custom="type {type:default;}" from kraken serialization.
This module reclassifies lines that fall outside the main text column as
custom="type {type:margin;}" using a positional heuristic.

Interlinear insertions are left as default lines — the LLM handles them from
context and the user does not require a separate interlinear type.

Heuristic
---------
A line is tagged as margin when both conditions hold:
  1. Its baseline length is < 35% of the page-median baseline length.
  2. It lies completely outside the main column:
       left margin  → x_max < Q1(all x_mins)
       right margin → x_min > Q3(all x_maxs)

This is conservative enough to avoid false positives on interlinear insertions
(which are short but horizontally overlap the main text block).
"""

from __future__ import annotations

import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path


def _xml_namespace(element: ET.Element) -> str:
    m = re.match(r"\{.*\}", element.tag)
    return m.group(0)[1:-1] if m else ""


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Return the pct-th percentile of an already-sorted list."""
    if not sorted_vals:
        return 0.0
    idx = pct / 100.0 * (len(sorted_vals) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def tag_margin_lines(xml_path: Path) -> int:
    """Rewrite xml_path in-place, tagging margin TextLines.

    Returns the number of lines tagged as margin.
    """
    xml_path = Path(xml_path)
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    ns_uri = _xml_namespace(root)
    ns = {"ns": ns_uri}
    ET.register_namespace("", ns_uri)

    all_lines = root.findall(".//ns:TextLine", ns)
    if len(all_lines) < 4:
        return 0

    # Parse per-line x-ranges from Baseline points
    parsed: list[tuple[int, int, ET.Element]] = []  # (x_min, x_max, element)
    for tl in all_lines:
        bl = tl.find("ns:Baseline", ns)
        if bl is None:
            continue
        pts = [
            int(p.split(",")[0])
            for p in bl.get("points", "").split()
            if "," in p
        ]
        if pts:
            parsed.append((min(pts), max(pts), tl))

    if len(parsed) < 4:
        return 0

    x_mins = sorted(p[0] for p in parsed)
    x_maxs = sorted(p[1] for p in parsed)
    lengths = [xx - xn for xn, xx, _ in parsed]
    med_len = statistics.median(lengths)

    # Main column: Q1 of left-edges and Q3 of right-edges
    q1_xmin = _percentile(x_mins, 25)
    q3_xmax = _percentile(x_maxs, 75)

    tagged = 0
    for xn, xx, tl in parsed:
        length = xx - xn
        is_short = length < 0.35 * med_len
        is_left_margin = xx < q1_xmin
        is_right_margin = xn > q3_xmax
        if is_short and (is_left_margin or is_right_margin):
            tl.set("custom", "type {type:margin;}")
            tagged += 1

    if tagged:
        tree.write(str(xml_path), xml_declaration=True, encoding="utf-8")
    return tagged
