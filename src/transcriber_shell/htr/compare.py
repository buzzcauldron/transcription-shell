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


@dataclass
class PerPageDelta:
    stem: str
    base_cer: float | None
    cand_cer: float | None
    delta_cer: float | None  # negative = candidate is BETTER (lower error)
    base_wer: float | None
    cand_wer: float | None
    delta_wer: float | None


def _per_page_cer(result: EvalResult) -> dict[str, tuple[float, float]]:
    """Pull per-page CER/WER out of an EvalResult. Returns {stem: (cer, wer)}."""
    out: dict[str, tuple[float, float]] = {}
    tx = result.transcription
    if tx is None or not tx.per_page:
        return out
    for entry in tx.per_page:
        # ketos test reports use various keys; try common ones
        stem = (
            entry.get("stem")
            or entry.get("name")
            or entry.get("page")
            or Path(str(entry.get("file") or entry.get("path") or "")).stem
        )
        if not stem:
            continue
        # char_accuracy → CER%; word_accuracy → WER%. Some keys are accuracies; we want errors.
        cer = entry.get("char_error_rate")
        if cer is None and "char_accuracy" in entry:
            cer = (1.0 - float(entry["char_accuracy"])) * 100
        wer = entry.get("word_error_rate")
        if wer is None and "word_accuracy" in entry:
            wer = (1.0 - float(entry["word_accuracy"])) * 100
        if cer is None:
            continue
        out[stem] = (float(cer), float(wer) if wer is not None else float("nan"))
    return out


def compare_models(
    base_model: Path,
    candidate_model: Path,
    gt: Path,
    *,
    seg_model: Path | None = None,
    device: str = "cpu",
    centroid_match_px: int = 8,
) -> dict[str, Any]:
    """Run both models on the same GT set and return aggregates + per-page deltas."""
    base_res = evaluate(
        base_model, gt,
        seg_model=seg_model, device=device, centroid_match_px=centroid_match_px,
    )
    cand_res = evaluate(
        candidate_model, gt,
        seg_model=seg_model, device=device, centroid_match_px=centroid_match_px,
    )

    base_pp = _per_page_cer(base_res)
    cand_pp = _per_page_cer(cand_res)
    stems = sorted(set(base_pp) | set(cand_pp))

    deltas: list[PerPageDelta] = []
    for stem in stems:
        b = base_pp.get(stem)
        c = cand_pp.get(stem)
        delta_cer = None if (b is None or c is None) else c[0] - b[0]
        delta_wer = None if (b is None or c is None) else c[1] - b[1]
        deltas.append(PerPageDelta(
            stem=stem,
            base_cer=b[0] if b else None,
            cand_cer=c[0] if c else None,
            delta_cer=delta_cer,
            base_wer=b[1] if b else None,
            cand_wer=c[1] if c else None,
            delta_wer=delta_wer,
        ))

    valid = [d for d in deltas if d.delta_cer is not None]
    n = len(valid)
    n_wins = sum(1 for d in valid if d.delta_cer < 0)
    n_losses = sum(1 for d in valid if d.delta_cer > 0)
    mean_delta_cer = (sum(d.delta_cer for d in valid) / n) if n else 0.0

    # Aggregate CER/WER from EvalResult if available
    base_overall = base_res.transcription
    cand_overall = cand_res.transcription
    base_cer_total = (1.0 - base_overall.char_accuracy) * 100 if base_overall else None
    cand_cer_total = (1.0 - cand_overall.char_accuracy) * 100 if cand_overall else None

    return {
        "base_model": str(base_model),
        "candidate_model": str(candidate_model),
        "gt": str(gt),
        "n_pages": n,
        "n_candidate_wins": n_wins,
        "n_candidate_losses": n_losses,
        "mean_delta_cer": round(mean_delta_cer, 3),
        "base_cer_total": (round(base_cer_total, 3) if base_cer_total is not None else None),
        "candidate_cer_total": (round(cand_cer_total, 3) if cand_cer_total is not None else None),
        "verdict": _verdict(mean_delta_cer, n_wins, n_losses, n),
        "per_page": [
            {
                "stem": d.stem,
                "base_cer": d.base_cer,
                "cand_cer": d.cand_cer,
                "delta_cer": d.delta_cer,
                "base_wer": d.base_wer,
                "cand_wer": d.cand_wer,
                "delta_wer": d.delta_wer,
            }
            for d in deltas
        ],
    }


def _verdict(mean_delta: float, wins: int, losses: int, n: int) -> str:
    """Plain-language summary of the comparison."""
    if n == 0:
        return "no comparable pages"
    if mean_delta < -0.5 and wins > losses:
        return "candidate clearly better"
    if mean_delta > 0.5 and losses > wins:
        return "candidate clearly worse"
    if abs(mean_delta) <= 0.5:
        return "candidate roughly equivalent to base"
    return "mixed: page-by-page check recommended"


def format_compare_report(result: dict[str, Any], *, as_json: bool = False) -> str:
    """Format compare-models output for the terminal."""
    if as_json:
        import json
        return json.dumps(result, indent=2)

    lines: list[str] = []
    lines.append("HTR comparison report")
    lines.append("─" * 60)
    lines.append(f"  base       : {result['base_model']}")
    lines.append(f"  candidate  : {result['candidate_model']}")
    lines.append(f"  gt         : {result['gt']}")
    lines.append(f"  pages      : {result['n_pages']}")
    base_cer = result.get("base_cer_total")
    cand_cer = result.get("candidate_cer_total")
    if base_cer is not None and cand_cer is not None:
        lines.append(f"  base CER   : {base_cer:.2f}%")
        lines.append(f"  cand CER   : {cand_cer:.2f}%")
        lines.append(f"  delta CER  : {cand_cer - base_cer:+.2f}% (negative = candidate better)")
    lines.append(f"  wins/losses: {result['n_candidate_wins']} / {result['n_candidate_losses']}")
    lines.append(f"  mean Δ CER : {result['mean_delta_cer']:+.3f}")
    lines.append(f"  verdict    : {result['verdict']}")
    lines.append("")
    lines.append(f"  {'page':<28} {'base':>7} {'cand':>7} {'Δ':>7}")
    for entry in result["per_page"]:
        b = f"{entry['base_cer']:7.2f}" if entry["base_cer"] is not None else "    n/a"
        c = f"{entry['cand_cer']:7.2f}" if entry["cand_cer"] is not None else "    n/a"
        d = f"{entry['delta_cer']:+7.2f}" if entry["delta_cer"] is not None else "    n/a"
        lines.append(f"  {entry['stem']:<28.28s} {b} {c} {d}")
    return "\n".join(lines) + "\n"
