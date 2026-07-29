"""Tests for reference corpus loading and stylo summary."""

from __future__ import annotations

from pathlib import Path

import pytest

from transcriber_shell.stylometry.reference_corpus import (
    default_reference_dir,
    genre_from_reference_filename,
    load_reference_chunks,
)
from transcriber_shell.stylometry.stylo_run import analyze_text


def test_genre_from_reference_filename() -> None:
    assert genre_from_reference_filename("computus_foo_01.txt") == "computus"
    assert genre_from_reference_filename("astronomy_bar.txt") == "astronomy"
    assert genre_from_reference_filename("natural-philosophy_x.txt") == "natural-philosophy"


@pytest.mark.skipif(default_reference_dir() is None, reason="no medieval mixed reference set")
def test_load_reference_chunks_has_computus() -> None:
    refs = load_reference_chunks(max_per_genre=5)
    assert "computus" in refs
    assert refs["computus"]


@pytest.mark.skipif(default_reference_dir() is None, reason="no medieval mixed reference set")
def test_analyze_text_returns_primary_secondary() -> None:
    # Short computus-ish synthetic text — still needs real refs for features.
    text = (
        "kalendas ianuarii littera dominicalis epacta concurrentes "
        "pascha luna aureo numero et in anno domini "
    ) * 40
    summary = analyze_text(text)
    assert summary.primary_register
    assert summary.secondary_content
    assert summary.n_words > 0
    assert "genre-mixed" in summary.note
