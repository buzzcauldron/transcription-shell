"""Tests for PageXML baseline comparison (reference vs hypothesis)."""

from __future__ import annotations

from pathlib import Path

from transcriber_shell.xml_tools.lines_compare import (
    chamfer_distance_px,
    compare_lines_xml,
    extract_textline_baselines,
    match_baselines,
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


def test_extract_and_compare_identical(tmp_path: Path) -> None:
    pts = "0,10 50,10 100,10"
    xml = _tl_xml([pts, "0,30 100,30"])
    p = tmp_path / "a.xml"
    p.write_text(xml, encoding="utf-8")
    polys = extract_textline_baselines(p)
    assert len(polys) == 2
    r = compare_lines_xml(p, p, centroid_match_px=5.0)
    assert r.reference_lines == 2
    assert r.hypothesis_lines == 2
    assert r.matched_pairs == 2
    assert r.recall_vs_reference == 1.0
    assert r.precision_vs_reference == 1.0
    assert r.mean_chamfer_px is not None
    assert r.mean_chamfer_px < 1.0


def test_compare_shifted_hypothesis(tmp_path: Path) -> None:
    ref = tmp_path / "ref.xml"
    hyp = tmp_path / "hyp.xml"
    ref.write_text(
        _tl_xml(["10,10 90,10", "10,40 90,40"]),
        encoding="utf-8",
    )
    hyp.write_text(
        _tl_xml(["12,10 92,10", "12,40 92,40"]),
        encoding="utf-8",
    )
    r = compare_lines_xml(ref, hyp, centroid_match_px=50.0)
    assert r.matched_pairs == 2
    assert r.mean_chamfer_px is not None
    assert r.mean_chamfer_px < 5.0


def test_chamfer_identical_polylines() -> None:
    p = [(0.0, 0.0), (10.0, 0.0)]
    d = chamfer_distance_px(p, p)
    assert d < 0.01


def test_match_centroid_threshold() -> None:
    ref = [[(0, 0), (10, 0)]]
    hyp = [[(500, 500), (510, 500)]]
    pairs, ur, uh = match_baselines(ref, hyp, centroid_match_px=10.0)
    assert pairs == []
    assert ur == [0]
    assert uh == [0]
