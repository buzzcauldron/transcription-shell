"""Tests for PageXML line parsing."""

from __future__ import annotations

from pathlib import Path

from transcriber_shell.htr.pagexml_lines import iter_text_lines, line_bboxes

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">
  <Page imageWidth="100" imageHeight="200">
    <TextRegion id="r1">
      <TextLine id="l1">
        <Coords points="1,2 90,2 90,20 1,20"/>
        <TextEquiv><Unicode>in principio</Unicode></TextEquiv>
      </TextLine>
    </TextRegion>
  </Page>
</PcGts>
"""


def test_iter_text_lines(tmp_path: Path) -> None:
    xml = tmp_path / "page.xml"
    xml.write_text(SAMPLE, encoding="utf-8")
    recs = iter_text_lines(xml)
    assert len(recs) == 1
    assert recs[0].text == "in principio"
    assert recs[0].bbox == (1, 2, 90, 20)
    assert line_bboxes(xml) == [(1, 2, 90, 20)]
