"""expand-diplomatic bridge (dry-run, no API)."""

from __future__ import annotations

from pathlib import Path

import pytest

from transcriber_shell.config import Settings
from transcriber_shell.expand.bridge import (
    build_pagexml_with_lines,
    expand_pagexml_lines,
    expand_pagexml_string,
    extract_unicode_lines,
    maybe_run_expand_stage,
    resolve_expand_root,
    should_run_expand,
)


@pytest.fixture
def expand_root() -> Path:
    root = resolve_expand_root()
    if not (root / "expand_diplomatic" / "expander.py").is_file():
        pytest.skip("expand-diplomatic checkout not found")
    return root


def test_should_run_expand_diplomatic_only() -> None:
    s = Settings(expand_diplomatic_enabled=True)
    assert should_run_expand({"normalizationMode": "diplomatic"}, s)
    assert not should_run_expand({"normalizationMode": "normalized"}, s)
    assert not should_run_expand({"normalizationMode": "diplomatic"}, Settings())


def test_build_and_extract_pagexml_lines() -> None:
    xml = build_pagexml_with_lines("page.jpg", 100, 200, ["dñs rex", "p̃benda"])
    assert "Unicode" in xml
    lines = extract_unicode_lines(xml)
    assert lines == ["dñs rex", "p̃benda"]


def test_expand_pagexml_dry_run(expand_root: Path) -> None:
    settings = Settings(
        expand_diplomatic_enabled=True,
        expand_diplomatic_root=expand_root,
        expand_diplomatic_dry_run=True,
        expand_diplomatic_backend="rules",
    )
    xml_in = build_pagexml_with_lines("p.jpg", 50, 50, ["dñs"])
    xml_out = expand_pagexml_string(xml_in, settings)
    assert "Unicode" in xml_out
    assert extract_unicode_lines(xml_out) == ["dñs"]


def test_expand_pagexml_lines_dry_run(expand_root: Path) -> None:
    settings = Settings(
        expand_diplomatic_root=expand_root,
        expand_diplomatic_dry_run=True,
        expand_diplomatic_backend="rules",
    )
    _xml, lines = expand_pagexml_lines("p.jpg", 80, 120, ["a", "b"], settings)
    assert lines == ["a", "b"]


def test_maybe_run_expand_skips_normalized(tmp_path: Path) -> None:
    yaml_path = tmp_path / "x_transcription.yaml"
    yaml_path.write_text(
        "transcriptionOutput:\n  protocolVersion: '1.1.0'\n  segments: []\n",
        encoding="utf-8",
    )
    s = Settings(expand_diplomatic_enabled=True)
    tei, txt, warns = maybe_run_expand_stage(
        yaml_path, {"normalizationMode": "normalized"}, s
    )
    assert tei is None and txt is None and not warns
