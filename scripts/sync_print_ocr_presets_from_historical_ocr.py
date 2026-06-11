#!/usr/bin/env python3
"""Regenerate print_ocr_presets.yaml from historical-ocr document_types/print/*.yaml."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

_SCRIPT = Path(__file__).resolve().parent
_SHELL_ROOT = _SCRIPT.parent
_OUT = _SHELL_ROOT / "scripts" / "latin_ms" / "document_types" / "print_ocr_presets.yaml"

# historical-ocr print type name → transcription-shell doc_type
_NAME_ALIASES: dict[str, str] = {
    "twentieth_century": "twentieth_century_print",
    "contemporary_print": "twentieth_century_print",
    "modern_historical": "twentieth_century_print",
    "nineteenth_century": "nineteenth_century_english_copperplate",
    "humanist_roman": "early_modern_latin",
    "eebo_blackletter": "early_modern_latin",
    "enlightenment_antiqua": "early_modern_english",
    "german_fraktur": "german_fraktur",
}


def _find_historical_ocr_root(explicit: Path | None) -> Path:
    if explicit and explicit.is_dir():
        return explicit.resolve()
    for cand in (
        _SHELL_ROOT.parent / "historical ocr",
        _SHELL_ROOT.parent / "historical-ocr",
        Path.home() / "Projects" / "historical ocr",
        Path.home() / "Projects" / "historical-ocr",
    ):
        if (cand / "document_types" / "print").is_dir():
            return cand.resolve()
    raise FileNotFoundError("historical-ocr checkout not found — set --historical-ocr-root")


def _shell_doc_key(data: dict[str, Any]) -> str:
    shell = data.get("shell") or {}
    if isinstance(shell, dict) and shell.get("doc_type"):
        return str(shell["doc_type"])
    name = str(data.get("name") or "")
    return _NAME_ALIASES.get(name, name)


def _mapping_priority(data: dict[str, Any], key: str) -> int:
    """Higher wins when multiple historical-ocr profiles map to one shell doc_type."""
    name = str(data.get("name") or "")
    shell_dt = (data.get("shell") or {}).get("doc_type")
    if name == key or shell_dt == key:
        return 3
    if shell_dt:
        return 2
    if _NAME_ALIASES.get(name) == key:
        return 1
    return 0


def _preset_from_print_yaml(data: dict[str, Any]) -> dict[str, Any]:
    ocr = data.get("ocr") or {}
    if not isinstance(ocr, dict):
        return {}
    preset: dict[str, Any] = {}
    if ocr.get("lang"):
        preset["tesseract_lang"] = str(ocr["lang"])
    if ocr.get("psm") is not None:
        preset["tesseract_psm"] = int(ocr["psm"])
    pre = ocr.get("preprocess") or {}
    if isinstance(pre, dict) and pre:
        preset["htr_preprocess_enabled"] = True
        if pre.get("autocontrast"):
            preset["htr_preprocess_contrast"] = 2.0
            preset["htr_preprocess_invert"] = True
        if pre.get("sharpen"):
            preset["htr_preprocess_sharpen"] = True
        if pre.get("grayscale"):
            preset["htr_preprocess_invert"] = True
    elif ocr.get("lang"):
        preset["htr_preprocess_enabled"] = True
        preset["htr_preprocess_invert"] = True
        preset.setdefault("htr_preprocess_contrast", 1.5)
    return preset


def build_presets(hist_root: Path) -> dict[str, Any]:
    print_dir = hist_root / "document_types" / "print"
    doc_types: dict[str, dict[str, Any]] = {}
    sources: dict[str, str] = {}
    sources_prio: dict[str, int] = {}

    for path in sorted(print_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or not data.get("name"):
            continue
        key = _shell_doc_key(data)
        preset = _preset_from_print_yaml(data)
        if not preset:
            continue
        prio = _mapping_priority(data, key)
        if key not in doc_types or prio >= sources_prio.get(key, -1):
            doc_types[key] = preset
            sources[key] = str(data["name"])
            sources_prio[key] = prio

    return {
        "doc_types": doc_types,
        "finetune": {
            "lang": "lat_pre1800",
            "candidates": [
                "${HOME}/Projects/historical ocr/models/lat_pre1800.traineddata",
                "${HOME}/Projects/historical-ocr/models/lat_pre1800.traineddata",
                "${HISTORICAL_OCR_ROOT}/models/lat_pre1800.traineddata",
                "${HISTORICAL_OCR_ROOT}/models/histnews.traineddata",
                "${LATIN_MS_WORKSPACE}/models/lat_pre1800.traineddata",
                "${TRANSCRIBER_SHELL_ROOT}/models/lat_pre1800.traineddata",
                "${TRANSCRIBER_SHELL_ROOT}/models/tessdata/lat_pre1800.traineddata",
            ],
        },
        "_sync": {
            "source": "historical-ocr document_types/print/",
            "historical_ocr_root": str(hist_root),
            "mapped_from": sources,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--historical-ocr-root", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=_OUT)
    ap.add_argument("--check", action="store_true", help="Exit 1 if out file would change")
    args = ap.parse_args()

    hist = _find_historical_ocr_root(args.historical_ocr_root)
    payload = build_presets(hist)
    header = (
        "# Print OCR runtime presets — synced from historical-ocr document_types/print/.\n"
        "# Regenerate: python scripts/sync_print_ocr_presets_from_historical_ocr.py\n"
        "# Applied by doc_type_apply for listed doc_types.\n\n"
    )
    body = yaml.safe_dump(
        {k: v for k, v in payload.items() if not k.startswith("_")},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    new_text = header + body

    if args.check and args.out.is_file() and args.out.read_text(encoding="utf-8") == new_text:
        print(f"[ok] {args.out} up to date ({len(payload['doc_types'])} doc types)")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(new_text, encoding="utf-8")
    print(f"[sync] wrote {args.out} ({len(payload['doc_types'])} doc types from {hist})")
    for key, src in sorted((payload.get("_sync") or {}).get("mapped_from", {}).items()):
        print(f"  {key} ← {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
