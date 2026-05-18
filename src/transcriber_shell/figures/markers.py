"""Insert ``[fig:id]`` markers into a finished transcription YAML.

We use the PageXML TextLine coordinates to map each figure's vertical
position to a line number, then locate the protocol segment whose
``lineRange`` contains that line and inject the marker into ``segment.text``
between the right pair of lines.

Output: the original YAML file rewritten in place with two changes —
``segments[i].text`` gets ``[fig:<id>]`` inserted at the correct position,
and a top-level ``figures:`` list is added with crop metadata.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import yaml

from transcriber_shell.figures.base import FigureResult


def _xml_namespace(element: ET.Element) -> str:
    m = re.match(r"\{.*\}", element.tag)
    return m.group(0)[1:-1] if m else ""


def _line_centers_y(lines_xml_path: Path) -> list[tuple[int, float]]:
    """Return [(line_number_1based, y_center_px), …] in document order.

    Skips lines tagged as margin (``custom="type {type:margin;}"``).
    """
    tree = ET.parse(str(lines_xml_path))
    root = tree.getroot()
    ns = {"ns": _xml_namespace(root)}
    out: list[tuple[int, float]] = []
    n = 0
    for line in root.findall(".//ns:TextLine", ns):
        if line.get("custom") == "type {type:margin;}":
            continue
        coords = line.find("ns:Coords", ns)
        if coords is None or not coords.get("points"):
            continue
        ys: list[float] = []
        for tok in coords.get("points", "").split():
            if "," not in tok:
                continue
            try:
                ys.append(float(tok.split(",", 1)[1]))
            except ValueError:
                continue
        if not ys:
            continue
        n += 1
        out.append((n, sum(ys) / len(ys)))
    return out


def _figure_anchor_line(
    figure_bbox: tuple[int, int, int, int],
    line_centers: list[tuple[int, float]],
) -> int:
    """Return the 1-based line number the figure should appear *after*.

    Picks the line whose y-center is just above the figure's top edge.
    Returns 0 if the figure sits above the first line (marker goes at the top
    of the matching segment), or the last line number if it sits below all
    lines (marker goes at the bottom).

    Limitation: this is a y-only heuristic. For multi-column pages, lines
    from column N+1 can be at the same y as lines in column N, so a figure
    sitting in column 2 may anchor against a column 1 line and land in a
    misleading segment. Acceptable for single-column body text (the common
    case); improving multi-column placement is a TODO once we expose a
    column hint from the lineation backend.
    """
    if not line_centers:
        return 0
    top_y = float(figure_bbox[1])
    # Lines whose center is strictly above the figure's top.
    above = [n for (n, yc) in line_centers if yc < top_y]
    if not above:
        return 0
    return max(above)


def _insert_marker_in_segment_text(text: str, after_line_in_segment_idx: int, marker: str) -> str:
    """Insert ``marker`` on its own line into the multi-line ``text`` after
    the (0-based) ``after_line_in_segment_idx``.

    If ``after_line_in_segment_idx < 0`` the marker is prepended; if it is
    >= number of lines the marker is appended.
    """
    lines = text.split("\n")
    # Preserve any trailing empty line semantics by working on a list copy.
    insertion_point = max(0, min(len(lines), after_line_in_segment_idx + 1))
    lines.insert(insertion_point, marker)
    return "\n".join(lines)


def insert_markers(
    *,
    yaml_path: Path,
    lines_xml_path: Path | None,
    figures: Iterable[FigureResult],
) -> tuple[int, int]:
    """Rewrite ``yaml_path`` in place to add ``[fig:id]`` markers + figures section.

    Returns ``(markers_inserted, figures_recorded)``.
    """
    figs = list(figures)
    if not figs:
        return 0, 0

    yaml_path = Path(yaml_path).expanduser().resolve()
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    root = data.get("transcriptionOutput") if isinstance(data, dict) and "transcriptionOutput" in data else data
    if not isinstance(root, dict):
        return 0, 0

    segments = root.get("segments")
    if not isinstance(segments, list):
        segments = []

    # Build the line→segment map from segments' lineRange.
    seg_for_line: dict[int, int] = {}  # line_no_1based → segment_idx
    for seg_idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            continue
        lr = seg.get("lineRange")
        if isinstance(lr, list) and len(lr) == 2:
            try:
                lo, hi = int(lr[0]), int(lr[1])
            except (TypeError, ValueError):
                continue
            for ln in range(lo, hi + 1):
                seg_for_line.setdefault(ln, seg_idx)

    line_centers = _line_centers_y(lines_xml_path) if lines_xml_path and Path(lines_xml_path).is_file() else []

    # Sort figures top-to-bottom so multiple insertions in the same segment land in reading order.
    figs_sorted = sorted(figs, key=lambda f: f.bbox[1])

    inserted = 0
    for f in figs_sorted:
        anchor_line = _figure_anchor_line(f.bbox, line_centers)
        # anchor_line == 0 → figure sits above the first detected line; target the FIRST segment.
        # otherwise → segment containing anchor_line; final fall-back is the last segment.
        seg_idx: int | None
        if anchor_line == 0:
            seg_idx = 0 if segments else None
        else:
            seg_idx = seg_for_line.get(anchor_line)
            if seg_idx is None and segments:
                seg_idx = len(segments) - 1
        if seg_idx is None:
            continue
        seg = segments[seg_idx]
        if not isinstance(seg, dict):
            continue
        text = seg.get("text", "")
        if not isinstance(text, str):
            continue
        lr = seg.get("lineRange") or [0, 0]
        try:
            seg_lo = int(lr[0])
        except (TypeError, ValueError):
            seg_lo = 1
        # Position inside this segment (0-based) — which segment-line we insert after.
        within = (anchor_line - seg_lo) if anchor_line > 0 else -1
        marker = f"[fig:{f.id}]"
        seg["text"] = _insert_marker_in_segment_text(text, within, marker)
        inserted += 1

    # Build the figures section.
    fig_section = []
    for f in figs_sorted:
        entry: dict = {
            "id": f.id,
            "bbox_page_px": list(f.bbox),
            "label": f.label,
            "detector_confidence": round(f.confidence, 3),
        }
        if f.crop_path is not None:
            entry["crop_path"] = str(f.crop_path)
        if f.notes:
            entry["notes"] = f.notes
        fig_section.append(entry)
    root["figures"] = fig_section

    yaml_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return inserted, len(figs_sorted)
