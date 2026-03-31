"""Tests for PAGE XML ground-truth validation vs image dimensions."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from transcriber_shell.xml_tools.validate_gt_pagexml import validate_gt_pagexml

PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"


def _xml(w: int, h: int, baseline: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="{PAGE_NS}">
  <Page imageFilename="t.png" imageWidth="{w}" imageHeight="{h}">
    <TextRegion id="tr">
      <TextLine id="l0"><Baseline points="{baseline}"/></TextLine>
    </TextRegion>
  </Page>
</PcGts>
"""


def test_validate_gt_ok(tmp_path: Path) -> None:
    img = tmp_path / "t.png"
    Image.new("RGB", (100, 80), color="white").save(img)
    xml = tmp_path / "t.xml"
    xml.write_text(_xml(100, 80, "0,40 100,40"), encoding="utf-8")
    ok, msgs = validate_gt_pagexml(xml, img)
    assert ok
    assert any("ok:" in m for m in msgs)


def test_validate_gt_dimension_mismatch(tmp_path: Path) -> None:
    img = tmp_path / "t.png"
    Image.new("RGB", (50, 50), color="white").save(img)
    xml = tmp_path / "t.xml"
    xml.write_text(_xml(100, 80, "0,40 100,40"), encoding="utf-8")
    ok, msgs = validate_gt_pagexml(xml, img)
    assert not ok
    assert any("error:" in m for m in msgs)


def test_validate_gt_no_baselines(tmp_path: Path) -> None:
    img = tmp_path / "t.png"
    Image.new("RGB", (10, 10), color="white").save(img)
    xml = tmp_path / "t.xml"
    xml.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="{PAGE_NS}">
  <Page imageFilename="t.png" imageWidth="10" imageHeight="10">
    <TextRegion id="tr"></TextRegion>
  </Page>
</PcGts>
""",
        encoding="utf-8",
    )
    ok, msgs = validate_gt_pagexml(xml, img)
    assert not ok
