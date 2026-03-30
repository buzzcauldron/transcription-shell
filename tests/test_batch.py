from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from transcriber_shell.pipeline.batch import (
    discover_images,
    resolve_lines_xml_for_image,
    sanitize_job_id,
)


def test_sanitize_job_id():
    assert sanitize_job_id("foo bar") == "foo_bar"
    assert sanitize_job_id("a" * 200) == "a" * 120


def test_discover_images_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        assert discover_images(d) == []


def test_discover_images_two_files():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "a.jpg").write_bytes(b"")
        (base / "b.png").write_bytes(b"")
        (base / "skip.txt").write_text("x")
        found = discover_images(d)
        assert len(found) == 2
        assert {p.name for p in found} == {"a.jpg", "b.png"}


def test_resolve_lines_xml_skip_gm_single_file(tmp_path: Path) -> None:
    xml = tmp_path / "shared.xml"
    xml.write_text("<root/>", encoding="utf-8")
    img = tmp_path / "page.jpg"
    img.write_bytes(b"")
    out = resolve_lines_xml_for_image(
        img,
        skip_gm=True,
        lines_xml=xml,
        lines_xml_dir=None,
        n_images=1,
    )
    assert out == xml.resolve()


def test_resolve_lines_xml_skip_gm_dir_match(tmp_path: Path) -> None:
    d = tmp_path / "xmls"
    d.mkdir()
    stem = tmp_path / "foo.jpg"
    stem.write_bytes(b"")
    (d / "foo.xml").write_text("<root/>", encoding="utf-8")
    out = resolve_lines_xml_for_image(
        stem,
        skip_gm=True,
        lines_xml=None,
        lines_xml_dir=d,
        n_images=2,
    )
    assert out == (d / "foo.xml").resolve()


def test_resolve_lines_xml_skip_gm_missing_dir_file_raises(tmp_path: Path) -> None:
    d = tmp_path / "xmls"
    d.mkdir()
    stem = tmp_path / "missing.jpg"
    stem.write_bytes(b"")
    with pytest.raises(FileNotFoundError):
        resolve_lines_xml_for_image(
            stem,
            skip_gm=True,
            lines_xml=None,
            lines_xml_dir=d,
            n_images=1,
        )
