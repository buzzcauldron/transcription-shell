"""Tests for historical-ocr-aligned print OCR presets."""

from __future__ import annotations

from transcriber_shell.doc_type_apply import apply_doc_type
from transcriber_shell.config import Settings
from transcriber_shell.htr.print_ocr_presets import settings_updates_for_doc_type


def test_german_fraktur_preset_enables_preprocess() -> None:
    upd = settings_updates_for_doc_type("german_fraktur")
    assert upd.get("htr_preprocess_enabled") is True
    assert "deu" in str(upd.get("tesseract_lang", ""))


def test_apply_doc_type_wires_print_preprocess_for_fraktur() -> None:
    s, _ = apply_doc_type("german_fraktur", Settings(), None)
    assert s.tesseract_enabled is True
    assert s.htr_preprocess_enabled is True
    assert s.htr_preprocess_contrast == 2.0
