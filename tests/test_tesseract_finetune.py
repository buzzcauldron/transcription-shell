"""Tests for fine-tuned Tesseract model install helpers."""

from __future__ import annotations

from pathlib import Path

from transcriber_shell.htr.tesseract_finetune import (
    install_finetune_tessdata,
    resolve_lang_with_finetune,
)


def test_resolve_lang_with_finetune_prepends_custom(tmp_path: Path) -> None:
    assert resolve_lang_with_finetune("lat+frk+eng", "lat_pre1800") == "lat_pre1800+lat+frk+eng"


def test_install_finetune_tessdata_copies(tmp_path: Path) -> None:
    src = tmp_path / "lat_pre1800.traineddata"
    src.write_bytes(b"fake")
    dest_dir = install_finetune_tessdata(src)
    assert dest_dir is not None
    assert (dest_dir / "lat_pre1800.traineddata").is_file()
