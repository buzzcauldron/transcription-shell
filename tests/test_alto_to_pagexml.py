"""Tests for Paris Bible ALTO → PAGE-XML conversion."""

from __future__ import annotations

from pathlib import Path

from scripts.alto_to_pagexml import alto_to_pagexml, convert_alto_corpus


SAMPLE_ALTO = """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#">
  <Layout>
    <Page WIDTH="100" HEIGHT="200">
      <PrintSpace>
        <TextLine ID="l1" HPOS="1" VPOS="2" WIDTH="90" HEIGHT="10"
                  BASELINE="1,10 91,10">
          <String CONTENT="in principio"/>
        </TextLine>
        <TextLine ID="l2" HPOS="1" VPOS="20" WIDTH="90" HEIGHT="10"
                  BASELINE="1,25 91,25">
          <String CONTENT="creauit"/>
        </TextLine>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
"""


def test_alto_to_pagexml_lines(tmp_path: Path) -> None:
    alto = tmp_path / "sample.xml"
    alto.write_text(SAMPLE_ALTO, encoding="utf-8")
    img = tmp_path / "sample.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    xml = alto_to_pagexml(alto, img)
    assert "in principio" in xml
    assert "creauit" in xml
    assert 'imageFilename="' in xml
    assert "TextLine" in xml
    assert "Baseline" in xml


def test_convert_alto_corpus(tmp_path: Path) -> None:
    alto_dir = tmp_path / "ALTO"
    images_dir = tmp_path / "Images"
    out_dir = tmp_path / "page-xml"
    alto_dir.mkdir()
    images_dir.mkdir()
    (alto_dir / "page1.xml").write_text(SAMPLE_ALTO.replace("sample", "page1"), encoding="utf-8")
    (images_dir / "page1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    ok, skip, err = convert_alto_corpus(alto_dir, images_dir, out_dir)
    assert ok == 1
    assert err == 0
    assert (out_dir / "page1.xml").is_file()
    assert "in principio" in (out_dir / "page1.xml").read_text(encoding="utf-8")
