"""Validate YAML/JSON transcriptionOutput using vendored validate_schema."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Tuple

import yaml

from transcriber_shell.config import Settings
from transcriber_shell.protocol_paths import ensure_protocol_benchmark_on_path

# Mirrors vendor/transcription-protocol/benchmark/validate_schema.py (protocol v1.1 output schema).
_VALID_POSITION = frozenset(
    {
        "body",
        "header",
        "footer",
        "margin_left",
        "margin_right",
        "margin_top",
        "margin_bottom",
        "interlinear",
        "footnote",
    }
)
_POSITION_ALIASES: dict[str, str] = {
    "main": "body",
    "main_body": "body",
    "center": "body",
    "left_margin": "margin_left",
    "right_margin": "margin_right",
    "top_margin": "margin_top",
    "bottom_margin": "margin_bottom",
    # Models often say "marginalia"; protocol vocabulary is margin_* only.
    "marginalia_left": "margin_left",
    "marginalia_right": "margin_right",
    "marginalia_top": "margin_top",
    "marginalia_bottom": "margin_bottom",
    "marginalia": "margin_left",
    "margin": "margin_left",
}
_VALID_PROTOCOL_VERSIONS = frozenset({"1.0.0", "1.1.0", "v1.0", "v1.1"})
_DEFAULT_PROTOCOL_VERSION = "1.1.0"
_VALID_ENGLISH_MODALITY = frozenset(
    {
        "unspecified",
        "insular_anglicana",
        "court_chancery",
        "secretary",
        "italic",
        "round_hand",
        "copperplate",
        "spencerian",
        "palmer_business",
        "school_cursive",
        "mixed_english_hands",
    }
)
_ENGLISH_MODALITY_ALIASES = {
    "cursive": "school_cursive",
}


def load_transcription_root(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict) and "transcriptionOutput" in data:
        out = data["transcriptionOutput"]
        return out if isinstance(out, dict) else None
    if isinstance(data, dict) and "metadata" in data and "segments" in data:
        return data
    return None


def load_yaml_or_json_path(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".json",):
        return json.loads(text)
    return yaml.safe_load(text)


def _normalize_position_value(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    s = raw.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = s.replace("-", "_")
    while "__" in s:
        s = s.replace("__", "_")
    s = _POSITION_ALIASES.get(s, s)
    return s if s in _VALID_POSITION else raw


def _normalize_confidence_value(raw: Any) -> Any:
    if isinstance(raw, str):
        return raw.strip().lower()
    return raw


def normalize_transcription_yaml_data(data: dict[str, Any]) -> None:
    """Normalize enum-like segment fields so validation matches common model drift (case, hyphens, synonyms).

    Mutates ``data`` in place (same structure as protocol YAML: top-level ``transcriptionOutput``).
    """
    root = data.get("transcriptionOutput")
    if not isinstance(root, dict) and "metadata" in data and "segments" in data:
        root = data
    if not isinstance(root, dict):
        return
    pv = root.get("protocolVersion")
    if not isinstance(pv, str) or pv.strip() not in _VALID_PROTOCOL_VERSIONS:
        root["protocolVersion"] = _DEFAULT_PROTOCOL_VERSION
    else:
        root["protocolVersion"] = pv.strip()
    meta = root.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
        root["metadata"] = meta
    if isinstance(meta, dict):
        mpv = meta.get("protocolVersion")
        if isinstance(mpv, str) and mpv.strip() in _VALID_PROTOCOL_VERSIONS:
            meta["protocolVersion"] = mpv.strip()
            root["protocolVersion"] = meta["protocolVersion"]
        else:
            meta["protocolVersion"] = root["protocolVersion"]
        rm = meta.get("runMode")
        if isinstance(rm, str):
            meta["runMode"] = rm.strip().lower()
        tl = meta.get("targetLanguage")
        ehm = meta.get("englishHandwritingModality")
        if isinstance(ehm, str):
            ehm_norm = ehm.strip().lower().replace("-", "_").replace(" ", "_")
            ehm_norm = _ENGLISH_MODALITY_ALIASES.get(ehm_norm, ehm_norm)
            if ehm_norm in _VALID_ENGLISH_MODALITY:
                meta["englishHandwritingModality"] = ehm_norm
        tl_s = tl.strip().lower() if isinstance(tl, str) else ""
        if tl_s and not tl_s.startswith("eng") and tl_s != "mixed":
            meta["englishHandwritingModality"] = None
    segs = root.get("segments")
    if not isinstance(segs, list):
        return
    for seg in segs:
        if not isinstance(seg, dict):
            continue
        if "position" in seg:
            seg["position"] = _normalize_position_value(seg["position"])
        if "confidence" in seg:
            seg["confidence"] = _normalize_confidence_value(seg["confidence"])


def validate_transcript_file(
    path: Path, settings: Settings | None = None
) -> Tuple[bool, list[str], list[str]]:
    ensure_protocol_benchmark_on_path(settings)
    from validate_schema import validate_transcription_output

    data = load_yaml_or_json_path(path)
    if isinstance(data, dict):
        normalize_transcription_yaml_data(data)
    root = load_transcription_root(data)
    if root is None:
        return False, ["top-level transcriptionOutput object not found"], []
    return validate_transcription_output(root)
