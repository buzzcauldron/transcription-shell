"""Bridge to medieval-proof (mst) for post-transcription genre and reasoning-mode classification.

medieval-proof is a sister project at ~/Projects/medieval-proof. This module either
imports it directly (if installed in the active venv) or falls back to subprocess.

Typical use after a batch run:
    from transcriber_shell.stylometry.medieval_proof import classify_transcription
    result = classify_transcription(transcription_yaml_path, model_path)
    # writes <stem>_classification.json alongside the YAML
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_MST_AVAILABLE: bool | None = None


def _mst_importable() -> bool:
    global _MST_AVAILABLE
    if _MST_AVAILABLE is None:
        try:
            import medieval_proof  # noqa: F401
            _MST_AVAILABLE = True
        except ImportError:
            _MST_AVAILABLE = False
    return _MST_AVAILABLE


def _extract_text_from_yaml(yaml_path: Path) -> str:
    """Pull plain text out of a transcription YAML without importing the full pipeline."""
    try:
        import yaml
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    root = data.get("transcriptionOutput", data)
    if not isinstance(root, dict):
        return ""
    segs = root.get("segments") or []
    return "\n".join(
        s["text"].strip()
        for s in segs
        if isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"].strip()
    )


def classify_text(text: str, model_path: Path) -> dict[str, Any]:
    """Classify text using medieval-proof, returning a result dict.

    Tries direct import first; falls back to writing a temp file and calling
    `mst classify --json` via subprocess.
    """
    if not text.strip():
        return {"error": "empty text"}

    if _mst_importable():
        return _classify_direct(text, model_path)
    return _classify_subprocess(text, model_path)


def _classify_direct(text: str, model_path: Path) -> dict[str, Any]:
    from medieval_proof.features import FeatureSchema, vectorize
    from medieval_proof.model import load_model
    from medieval_proof.reasoning_mode import score_reasoning_mode

    cal = load_model(model_path)
    schema = FeatureSchema(ngram_vocab=cal.metadata["ngram_vocab"])
    vec = vectorize(text, schema)
    probs = cal.predict_proba(vec)
    ranked = sorted(zip(cal.classes, probs.tolist()), key=lambda x: -x[1])

    rm = score_reasoning_mode(text)
    return {
        "genre": {"ranked": [{"label": c, "prob": round(p, 4)} for c, p in ranked]},
        "reasoning_mode": {
            "label": rm.label,
            "margin": round(rm.margin, 3),
            "dialogic": round(rm.dialogic, 3),
            "expository": round(rm.expository, 3),
            "tabular_density": round(rm.tabular_density, 3),
            "hits_dialogic": rm.hits_dialogic,
            "hits_expository": rm.hits_expository,
        },
    }


def _classify_subprocess(text: str, model_path: Path) -> dict[str, Any]:
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8", delete=False) as f:
        f.write(text)
        tmp = Path(f.name)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "medieval_proof.cli", "classify", str(tmp),
             "--model", str(model_path), "--json"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return json.loads(result.stdout)
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        tmp.unlink(missing_ok=True)


def classify_transcription(
    yaml_path: Path,
    model_path: Path,
    *,
    write_sidecar: bool = True,
) -> dict[str, Any]:
    """Classify a transcription YAML. Writes a *_classification.json sidecar by default.

    Returns the classification result dict (or {"error": ...} on failure).
    """
    text = _extract_text_from_yaml(yaml_path)
    result = classify_text(text, model_path)
    result["source_yaml"] = str(yaml_path)

    if write_sidecar and "error" not in result:
        sidecar = yaml_path.with_name(
            yaml_path.stem.replace("_transcription", "") + "_classification.json"
        )
        sidecar.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    return result


def classify_batch(
    yaml_paths: list[Path],
    model_path: Path,
    *,
    write_sidecars: bool = True,
    log_fn=None,
) -> list[dict[str, Any]]:
    """Classify a list of transcription YAMLs."""
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    results = []
    n = len(yaml_paths)
    for i, p in enumerate(yaml_paths, 1):
        _log(f"[{i}/{n}] classifying {p.name}")
        r = classify_transcription(p, model_path, write_sidecar=write_sidecars)
        if "error" in r:
            _log(f"[{i}/{n}] warn: {r['error']}")
        results.append(r)
    return results
