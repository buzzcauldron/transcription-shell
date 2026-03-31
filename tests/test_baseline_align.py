"""Tests for Glyph Machina baseline correction (hypothesis ← reference)."""

from __future__ import annotations

from pathlib import Path

from transcriber_shell.xml_tools.baseline_align import apply_glyph_machina_corrections
from transcriber_shell.xml_tools.lines_compare import (
    compare_lines_xml,
    extract_textline_baselines,
)

PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"


def _tl_xml(baselines: list[str]) -> str:
    lines = []
    for i, pts in enumerate(baselines):
        lines.append(
            f'    <TextLine id="l{i}"><Baseline points="{pts}"/></TextLine>'
        )
    inner = "\n".join(lines)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="{PAGE_NS}">
  <Page imageWidth="100" imageHeight="200">
    <TextRegion id="tr">
{inner}
    </TextRegion>
  </Page>
</PcGts>
"""


def test_apply_gm_replaces_shifted_baselines(tmp_path: Path) -> None:
    ref = tmp_path / "ref.xml"
    hyp = tmp_path / "hyp.xml"
    out = tmp_path / "out.xml"
    ref.write_text(
        _tl_xml(["10,10 90,10", "10,40 90,40"]),
        encoding="utf-8",
    )
    hyp.write_text(
        _tl_xml(["12,12 92,12", "12,42 92,42"]),
        encoding="utf-8",
    )
    apply_glyph_machina_corrections(hyp, ref, out, centroid_match_px=80.0)
    r = compare_lines_xml(ref, out, centroid_match_px=5.0)
    assert r.matched_pairs == 2
    assert r.mean_chamfer_px is not None and r.mean_chamfer_px < 1.0
    assert extract_textline_baselines(ref) == extract_textline_baselines(out)


def test_apply_gm_drops_extra_hypothesis_lines(tmp_path: Path) -> None:
    ref = tmp_path / "ref.xml"
    hyp = tmp_path / "hyp.xml"
    out = tmp_path / "out.xml"
    ref.write_text(_tl_xml(["0,10 100,10", "0,40 100,40"]), encoding="utf-8")
    hyp.write_text(
        _tl_xml(["0,10 100,10", "0,40 100,40", "0,70 100,70"]),
        encoding="utf-8",
    )
    apply_glyph_machina_corrections(hyp, ref, out, centroid_match_px=120.0)
    assert len(extract_textline_baselines(out)) == 2
    assert extract_textline_baselines(ref) == extract_textline_baselines(out)


def test_apply_gm_appends_missing_reference_lines(tmp_path: Path) -> None:
    ref = tmp_path / "ref.xml"
    hyp = tmp_path / "hyp.xml"
    out = tmp_path / "out.xml"
    ref.write_text(
        _tl_xml(["0,10 100,10", "0,40 100,40", "0,70 100,70"]),
        encoding="utf-8",
    )
    hyp.write_text(_tl_xml(["0,10 100,10", "0,40 100,40"]), encoding="utf-8")
    apply_glyph_machina_corrections(hyp, ref, out, centroid_match_px=120.0)
    assert len(extract_textline_baselines(out)) == 3
    assert extract_textline_baselines(ref) == extract_textline_baselines(out)
