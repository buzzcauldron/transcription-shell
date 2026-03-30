from __future__ import annotations

import tempfile
from pathlib import Path

from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
from transcriber_shell.xml_tools.pagexml_schema import validate_xsd_optional


def test_validate_lines_xml_counts_textline():
    xml = """<?xml version="1.0"?>
<root xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15">
  <TextRegion>
    <TextLine id="l1"/>
    <TextLine id="l2"/>
  </TextRegion>
</root>
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as f:
        f.write(xml)
        p = f.name
    try:
        ok, msgs, stats = validate_lines_xml(p, require_text_line=True)
        assert ok
        assert stats["text_line"] == 2
        assert stats["text_region"] == 1
    finally:
        Path(p).unlink(missing_ok=True)


def test_validate_xsd_requires_lxml_when_missing():
    import importlib.util

    if importlib.util.find_spec("lxml") is not None:
        return
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as fx:
        with tempfile.NamedTemporaryFile(suffix=".xsd", delete=False) as fs:
            ok, errs = validate_xsd_optional(Path(fx.name), Path(fs.name))
    assert ok is False
    assert any("lxml" in e for e in errs)
