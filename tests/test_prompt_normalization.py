"""Tests for prompt cfg normalizationMode vs diplomatic toggle."""

from __future__ import annotations

from pathlib import Path

from transcriber_shell.pipeline.run import (
    load_prompt_cfg,
    set_normalization_mode_for_diplomatic,
)


def test_set_normalization_mode_for_diplomatic_false() -> None:
    cfg: dict = {"normalizationMode": "diplomatic"}
    set_normalization_mode_for_diplomatic(cfg, diplomatic=False)
    assert cfg["normalizationMode"] == "normalized"


def test_set_normalization_mode_for_diplomatic_true() -> None:
    cfg: dict = {"normalizationMode": "normalized"}
    set_normalization_mode_for_diplomatic(cfg, diplomatic=True)
    assert cfg["normalizationMode"] == "diplomatic"


def test_example_fixture_normalized_then_toggle() -> None:
    path = Path(__file__).resolve().parents[1] / "fixtures" / "prompt.example.yaml"
    cfg = load_prompt_cfg(path)
    assert cfg.get("normalizationMode") == "normalized"
    set_normalization_mode_for_diplomatic(cfg, diplomatic=True)
    assert cfg["normalizationMode"] == "diplomatic"
    set_normalization_mode_for_diplomatic(cfg, diplomatic=False)
    assert cfg["normalizationMode"] == "normalized"
