"""Tests for Tesseract OCR corpus preparation helpers."""

from __future__ import annotations

from pathlib import Path

from scripts.prepare_tesseract_ocr_corpus import (
    _gt4_image_for_txt,
    _normalize_text,
)


def test_normalize_text_strips_bom() -> None:
    assert _normalize_text("\ufeffhello") == "hello"


def test_gt4_image_for_txt_prefers_nrm(tmp_path: Path) -> None:
    gt = tmp_path / "00001.gt.txt"
    gt.write_text("line text\n", encoding="utf-8")
    nrm = tmp_path / "00001.nrm.png"
    nrm.write_bytes(b"\x89PNG\r\n\x1a\n")
    bin_png = tmp_path / "00001.bin.png"
    bin_png.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert _gt4_image_for_txt(gt) == nrm
