"""Tests for document-type → settings/GUI preset wiring."""

from __future__ import annotations

from transcriber_shell.config import Settings
from transcriber_shell.doc_type_apply import (
    apply_doc_type,
    form_preset_for_doc_type,
    prefer_tesseract_ocr,
)
from transcriber_shell.document_types import load_doc_type


def test_print_doc_type_prefers_tesseract() -> None:
    spec = load_doc_type("twentieth_century_print")
    assert prefer_tesseract_ocr(spec) is True


def test_manuscript_doc_type_uses_kraken_htr() -> None:
    spec = load_doc_type("nineteenth_century_english_copperplate")
    assert prefer_tesseract_ocr(spec) is False
    settings, _ = apply_doc_type("nineteenth_century_english_copperplate", Settings(), None)
    assert settings.htr_combination == "kraken_htr"


def test_print_doc_type_enables_tesseract_combination() -> None:
    settings, prompt = apply_doc_type("twentieth_century_print", Settings(), None)
    assert settings.tesseract_enabled is True
    assert settings.htr_combination == "tesseract_htr"
    assert prompt is not None
    assert "prompt_modern_print" in prompt


def test_form_preset_resolves_provider_and_model() -> None:
    preset = form_preset_for_doc_type("medieval_latin_legal")
    assert preset.provider == "anthropic"
    assert preset.model_id is not None
    assert preset.prompt_path is not None
