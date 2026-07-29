"""Gate for promoting ``llm_mode=correct`` to a doc-type default.

Computus HTR val CER is already strong (~5.7%), but ketos validation is not a
frozen held-out eval. Until ``metrics.held_out_ready`` is true on the registry
entry (and CER/WER clear thresholds), we recommend correct mode without silently
changing the default away from ``full``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Align with docs/model-goals.md Phase 2 (LLM-correct usable) — ink CER/WER.
DEFAULT_MAX_CER = 0.15
DEFAULT_MAX_WER = 0.50

_MODELS_DIR = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "latin_ms"
    / "document_types"
    / "models"
)


@dataclass(frozen=True)
class CorrectModeGate:
    passed: bool
    recommended: bool
    cer: float | None
    wer: float | None
    reason: str


def _cer_wer_from_metrics(metrics: dict[str, Any]) -> tuple[float | None, float | None]:
    cer = metrics.get("held_out_cer")
    wer = metrics.get("held_out_wer")
    if cer is None and "val_accuracy" in metrics:
        try:
            cer = 1.0 - float(metrics["val_accuracy"])
        except (TypeError, ValueError):
            cer = None
    if wer is None and "val_word_accuracy" in metrics:
        try:
            wer = 1.0 - float(metrics["val_word_accuracy"])
        except (TypeError, ValueError):
            wer = None
    per = metrics.get("per_corpus_cer") or {}
    if isinstance(per, dict) and per and cer is None:
        try:
            vals = [float(v) for v in per.values() if v is not None]
            if vals:
                cer = sum(vals) / len(vals)
        except (TypeError, ValueError):
            pass
    return cer, wer


def evaluate_correct_mode_gate(
    metrics: dict[str, Any] | None,
    *,
    max_cer: float = DEFAULT_MAX_CER,
    max_wer: float = DEFAULT_MAX_WER,
) -> CorrectModeGate:
    """Return whether correct mode may become the silent default."""
    m = metrics or {}
    cer, wer = _cer_wer_from_metrics(m)
    recommended = bool(m.get("recommend_correct_mode", False))
    if cer is not None and cer <= max_cer:
        recommended = True

    held_out_ready = bool(m.get("held_out_ready", False))
    if not held_out_ready:
        return CorrectModeGate(
            passed=False,
            recommended=recommended or (cer is not None and cer <= max_cer),
            cer=cer,
            wer=wer,
            reason=(
                "held_out_ready is false — use llm_mode=correct explicitly; "
                "val metrics alone do not promote it to the silent default"
            ),
        )
    if cer is None or wer is None:
        return CorrectModeGate(
            passed=False,
            recommended=recommended,
            cer=cer,
            wer=wer,
            reason="held-out CER/WER missing",
        )
    if cer > max_cer or wer > max_wer:
        return CorrectModeGate(
            passed=False,
            recommended=False,
            cer=cer,
            wer=wer,
            reason=f"held-out CER/WER above gate (need CER≤{max_cer}, WER≤{max_wer})",
        )
    return CorrectModeGate(
        passed=True,
        recommended=True,
        cer=cer,
        wer=wer,
        reason="held-out CER/WER within gate",
    )


def load_model_metrics(name: str, models_dir: Path | None = None) -> dict[str, Any]:
    root = models_dir or _MODELS_DIR
    path = root / f"{name}.yaml"
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    metrics = dict(raw.get("metrics") or {})
    if "val_accuracy" in raw and "val_accuracy" not in metrics:
        metrics["val_accuracy"] = raw["val_accuracy"]
    if "val_word_accuracy" in raw and "val_word_accuracy" not in metrics:
        metrics["val_word_accuracy"] = raw["val_word_accuracy"]
    return metrics


def gate_for_registry_model(name: str, models_dir: Path | None = None) -> CorrectModeGate:
    """Load a model registry YAML by name and evaluate the gate."""
    metrics = load_model_metrics(name, models_dir=models_dir)
    if not metrics:
        return CorrectModeGate(False, False, None, None, f"unknown or empty metrics for {name!r}")
    return evaluate_correct_mode_gate(metrics)
