"""Compare two HTR models on a shared test set.

Runs `transcriber_shell.htr.eval.evaluate` for each model and emits the
per-page CER/WER delta. Tells us whether fine-tuning beats the base model
on the actual data we care about — a comparison ketos's own validation
loop can't make because it only sees one model at a time on an
in-distribution split.

Test set format: a directory of XML (PAGE or ALTO) files with matching
images. Same format `evaluate()` already accepts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from transcriber_shell.htr.eval import EvalResult, evaluate


def compare_models(
    base_model: Path,
    candidate_model: Path,
    gt: Path,
    *,
    seg_model: Path | None = None,
    device: str = "cpu",
    centroid_match_px: int = 8,
) -> dict[str, Any]:
    """Run both models on the same GT set, return aggregate CER/WER and verdict.

    `evaluate()` returns ketos's batch-aggregate metrics — not per-page. For
    per-page deltas, call this function once per single-XML subdirectory.
    """
    base_res = evaluate(
        base_model, gt,
        seg_model=seg_model, device=device, centroid_match_px=centroid_match_px,
    )
    cand_res = evaluate(
        candidate_model, gt,
        seg_model=seg_model, device=device, centroid_match_px=centroid_match_px,
    )

    bt = base_res.transcription
    ct = cand_res.transcription
    if bt is None or ct is None:
        return {
            "base_model": str(base_model),
            "candidate_model": str(candidate_model),
            "gt": str(gt),
            "error": "evaluate() returned no TranscriptionMetrics for one or both models",
            "base_warnings": base_res.warnings,
            "candidate_warnings": cand_res.warnings,
        }

    base_cer = bt.cer() * 100
    cand_cer = ct.cer() * 100
    base_wer = bt.wer() * 100 if bt.wer() is not None else None
    cand_wer = ct.wer() * 100 if ct.wer() is not None else None
    delta_cer = cand_cer - base_cer
    delta_wer = (cand_wer - base_wer) if (cand_wer is not None and base_wer is not None) else None

    return {
        "base_model": str(base_model),
        "candidate_model": str(candidate_model),
        "gt": str(gt),
        "n_lines": bt.num_lines,
        "base_cer": round(base_cer, 3),
        "candidate_cer": round(cand_cer, 3),
        "delta_cer": round(delta_cer, 3),
        "base_wer": (round(base_wer, 3) if base_wer is not None else None),
        "candidate_wer": (round(cand_wer, 3) if cand_wer is not None else None),
        "delta_wer": (round(delta_wer, 3) if delta_wer is not None else None),
        "verdict": _verdict(delta_cer),
    }


def _verdict(delta_cer: float) -> str:
    """Plain-language summary of the candidate's relative CER."""
    if delta_cer < -1.0:
        return "candidate clearly better (Δ < -1%)"
    if delta_cer < -0.2:
        return "candidate slightly better"
    if abs(delta_cer) <= 0.2:
        return "candidate roughly equivalent to base"
    if delta_cer > 1.0:
        return "candidate clearly worse (Δ > +1%)"
    return "candidate slightly worse"


def format_compare_report(result: dict[str, Any], *, as_json: bool = False) -> str:
    """Format compare-models output for the terminal."""
    if as_json:
        import json
        return json.dumps(result, indent=2)

    if "error" in result:
        return f"htr-compare error: {result['error']}\n"

    lines: list[str] = []
    lines.append("HTR comparison report")
    lines.append("─" * 60)
    lines.append(f"  base       : {result['base_model']}")
    lines.append(f"  candidate  : {result['candidate_model']}")
    lines.append(f"  gt         : {result['gt']}")
    lines.append(f"  lines      : {result['n_lines']}")
    lines.append("")
    lines.append(f"  base CER   : {result['base_cer']:7.3f}%")
    lines.append(f"  cand CER   : {result['candidate_cer']:7.3f}%")
    lines.append(f"  Δ CER      : {result['delta_cer']:+7.3f}%  (negative = candidate better)")
    if result.get("base_wer") is not None and result.get("candidate_wer") is not None:
        lines.append(f"  base WER   : {result['base_wer']:7.3f}%")
        lines.append(f"  cand WER   : {result['candidate_wer']:7.3f}%")
        lines.append(f"  Δ WER      : {result['delta_wer']:+7.3f}%")
    lines.append("")
    lines.append(f"  verdict    : {result['verdict']}")
    return "\n".join(lines) + "\n"
