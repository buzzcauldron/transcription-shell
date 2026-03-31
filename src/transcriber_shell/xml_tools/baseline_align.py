"""Replace local line baselines with Glyph Machina (reference) baselines where lines match."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path

from transcriber_shell.xml_tools.lines_compare import (
    extract_textline_baselines,
    match_baselines,
)


def _local_name(el: ET.Element) -> str:
    tag = el.tag
    if tag.startswith("{"):
        return tag.split("}", 1)[-1]
    return tag


def _format_baseline_points(poly: list[tuple[float, float]]) -> str:
    return " ".join(f"{int(round(x))},{int(round(y))}" for x, y in poly)


def _collect_textlines_with_baseline(root: ET.Element) -> list[tuple[ET.Element, ET.Element]]:
    """Document order: (TextLine element, Baseline element)."""
    out: list[tuple[ET.Element, ET.Element]] = []
    for el in root.iter():
        if _local_name(el) != "TextLine":
            continue
        bl = None
        for child in el:
            if _local_name(child) == "Baseline":
                bl = child
                break
        if bl is not None:
            out.append((el, bl))
    return out


def _first_text_region(root: ET.Element) -> ET.Element | None:
    for el in root.iter():
        if _local_name(el) == "TextRegion":
            return el
    return None


def _remove_textline_under_root(root: ET.Element, tl: ET.Element) -> None:
    for parent in root.iter():
        for i, c in enumerate(list(parent)):
            if c is tl:
                del parent[i]
                return
    raise ValueError("TextLine element not found in tree")


def apply_glyph_machina_corrections(
    hypothesis_path: str | Path,
    reference_path: str | Path,
    output_path: str | Path,
    *,
    centroid_match_px: float = 120.0,
) -> None:
    """Assume **reference** (Glyph Machina) baselines are fully correct.

    - For each line in the hypothesis that matches a reference line (by centroid),
      **replace** Baseline ``points`` with the reference polyline.
    - **Remove** hypothesis TextLines that do not match any reference line.
    - **Append** reference TextLines that had no hypothesis match (copy subtree from reference).

    Page / image metadata come from the hypothesis file; only baselines and line list are corrected.
    """
    hyp_path = Path(hypothesis_path)
    ref_path = Path(reference_path)
    out_path = Path(output_path)

    ref_polys = extract_textline_baselines(ref_path)
    hyp_polys = extract_textline_baselines(hyp_path)
    pairs, unmatched_ref, unmatched_hyp = match_baselines(
        ref_polys, hyp_polys, centroid_match_px=centroid_match_px
    )

    tree = ET.parse(hyp_path)
    root = tree.getroot()
    hyp_pairs = _collect_textlines_with_baseline(root)
    if len(hyp_pairs) != len(hyp_polys):
        raise ValueError("internal: hypothesis TextLine count mismatch vs extract_textline_baselines")

    ref_tree = ET.parse(ref_path)
    ref_root = ref_tree.getroot()
    ref_pairs = _collect_textlines_with_baseline(ref_root)
    if len(ref_pairs) != len(ref_polys):
        raise ValueError("internal: reference TextLine count mismatch vs extract_textline_baselines")

    # Apply matched reference baselines onto hypothesis Baseline elements
    for ri, hj, _ in pairs:
        hyp_pairs[hj][1].set("points", _format_baseline_points(ref_polys[ri]))

    # Remove hypothesis-only lines (unmatched hyp indices), from high index to low
    for hj in sorted(unmatched_hyp, reverse=True):
        tl_el = hyp_pairs[hj][0]
        _remove_textline_under_root(root, tl_el)

    # Append missing reference lines (unmatched ref)
    region = _first_text_region(root)
    if region is None:
        raise ValueError("hypothesis has no TextRegion to append into")
    for ri in sorted(unmatched_ref):
        tl_copy = copy.deepcopy(ref_pairs[ri][0])
        region.append(tl_copy)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
