"""Tests for llm_mode=correct promotion gate."""

from __future__ import annotations

from transcriber_shell.htr.correct_gate import evaluate_correct_mode_gate, gate_for_registry_model


def test_gate_blocks_without_held_out_ready() -> None:
    g = evaluate_correct_mode_gate(
        {
            "val_accuracy": 0.94,
            "val_word_accuracy": 0.76,
            "held_out_ready": False,
            "recommend_correct_mode": True,
        }
    )
    assert g.passed is False
    assert g.recommended is True
    assert g.cer is not None and g.cer < 0.1


def test_gate_passes_with_held_out() -> None:
    g = evaluate_correct_mode_gate(
        {
            "held_out_cer": 0.08,
            "held_out_wer": 0.30,
            "held_out_ready": True,
        }
    )
    assert g.passed is True
    assert g.recommended is True


def test_computus_registry_recommends_but_does_not_pass() -> None:
    g = gate_for_registry_model("gm-htr-computus_best")
    assert g.recommended is True
    assert g.passed is False
