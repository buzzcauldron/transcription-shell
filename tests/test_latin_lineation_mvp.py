"""Tests for examples/latin_lineation_mvp (dataset + model when torch is installed)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"


def _minimal_pagexml(baselines: list[str]) -> str:
    lines = "\n".join(
        f'      <TextLine id="l{i}"><Baseline points="{pts}"/></TextLine>'
        for i, pts in enumerate(baselines)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="{PAGE_NS}">
  <Page imageWidth="100" imageHeight="100">
    <TextRegion id="tr">
{lines}
    </TextRegion>
  </Page>
</PcGts>
"""


def test_extract_and_rasterize(tmp_path: Path) -> None:
    import sys

    root = Path(__file__).resolve().parents[1]
    mvp = root / "examples" / "latin_lineation_mvp" / "src"
    sys.path.insert(0, str(mvp))
    from latin_lineation_mvp.dataset import (
        extract_textline_baselines_from_xml,
        rasterize_baselines,
    )

    xml = tmp_path / "p.xml"
    xml.write_text(
        _minimal_pagexml(["0,50 100,50", "0,70 100,70"]),
        encoding="utf-8",
    )
    polys = extract_textline_baselines_from_xml(xml)
    assert len(polys) == 2
    m = rasterize_baselines(polys, 100, 100, line_width=4)
    assert m.shape == (2, 100, 100)
    assert m.max() <= 1.0 and m.min() >= 0.0
    assert m.sum() > 10


def test_find_page_pairs_and_filter(tmp_path: Path) -> None:
    import sys

    from PIL import Image

    root = Path(__file__).resolve().parents[1]
    mvp = root / "examples" / "latin_lineation_mvp" / "src"
    sys.path.insert(0, str(mvp))
    from latin_lineation_mvp.dataset import (
        filter_pairs_with_lines,
        find_page_pairs,
    )

    Image.new("RGB", (32, 32), color="white").save(tmp_path / "a.jpg")
    (tmp_path / "a.xml").write_text(
        _minimal_pagexml(["0,1 10,1"]),
        encoding="utf-8",
    )
    pairs = find_page_pairs(tmp_path)
    assert len(pairs) == 1
    f = filter_pairs_with_lines(pairs)
    assert len(f) == 1


def test_line_mask_unet_forward() -> None:
    torch = pytest.importorskip("torch", reason="torch not installed")
    root = Path(__file__).resolve().parents[1]
    mvp = root / "examples" / "latin_lineation_mvp" / "src"
    import sys

    sys.path.insert(0, str(mvp))
    from latin_lineation_mvp.model import LineMaskUNet

    m = LineMaskUNet(max_lines=16)
    x = torch.randn(1, 3, 256, 256)
    y = m(x)
    assert y.shape == (1, 16, 256, 256)
