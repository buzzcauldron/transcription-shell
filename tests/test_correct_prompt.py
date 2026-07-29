"""Tests for short HTR-correct prompts."""

from __future__ import annotations

from transcriber_shell.llm.correct_prompt import (
    build_correct_prompts,
    should_use_short_correct,
)


def test_should_use_short_correct_requires_htr_header() -> None:
    assert not should_use_short_correct("correct", "just a line hint")
    assert should_use_short_correct(
        "correct",
        "HTR machine-readable drafts (for cross-check only; output must still be full protocol YAML)\n\nfoo",
    )
    assert not should_use_short_correct("full", "HTR machine-readable drafts\n")


def test_build_correct_diplomatic_forbids_expansion() -> None:
    system, user = build_correct_prompts(
        line_hint="HTR machine-readable drafts\nline1",
        normalization_mode="diplomatic",
        language_hint="lat-Latn",
    )
    assert "DIPLOMATIC MODE" in system
    assert "Do NOT expand" in system
    assert "ẽt→et" in system  # mentioned as what not to do
    assert "Language/script context: lat-Latn" in user
    assert "HTR machine-readable drafts" in user


def test_build_correct_normalized_allows_expansion() -> None:
    system, _user = build_correct_prompts(
        line_hint="HTR machine-readable drafts\nline1",
        normalization_mode="normalized",
    )
    assert "NORMALIZED MODE" in system
    assert "expand common abbreviation" in system.lower() or "ẽt→et" in system
