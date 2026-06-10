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
        "table_row",
        "table_header",
    }
)
_POSITION_ALIASES: dict[str, str] = {
    "main": "body",
    "main_body": "body",
    "center": "body",
    "full_page": "body",
    "full_text": "body",
    "text": "body",
    "left_margin": "margin_left",
    "right_margin": "margin_right",
    "top_margin": "margin_top",
    "bottom_margin": "margin_bottom",
    # Bare direction words LLMs emit.
    "top": "margin_top",
    "bottom": "margin_bottom",
    "left": "margin_left",
    "right": "margin_right",
    # Centered header variants.
    "top_center": "header",
    "top_centered": "header",
    # Models often say "marginalia"; protocol vocabulary is margin_* only.
    "marginalia_left": "margin_left",
    "marginalia_right": "margin_right",
    "marginalia_top": "margin_top",
    "marginalia_bottom": "margin_bottom",
    "marginalia": "margin_left",
    "margin": "margin_left",
    # Models invent finer-grained marginalia positions (e.g. bottom-right corner);
    # collapse to the nearest protocol bucket so the validator passes.
    "marginalia_bottom_right": "margin_bottom",
    "marginalia_bottom_left": "margin_bottom",
    "marginalia_top_right": "margin_top",
    "marginalia_top_left": "margin_top",
    "margin_bottom_right": "margin_bottom",
    "margin_bottom_left": "margin_bottom",
    "margin_top_right": "margin_top",
    "margin_top_left": "margin_top",
    # Hyphenated and "corner" spellings LLMs produce for margin positions.
    "top_right_corner": "margin_top",
    "top_left_corner": "margin_top",
    "bottom_right_corner": "margin_bottom",
    "bottom_left_corner": "margin_bottom",
    "top_right": "margin_top",
    "top_left": "margin_top",
    "bottom_right": "margin_bottom",
    "bottom_left": "margin_bottom",
    # Models sometimes invent labels outside OUTPUT_SCHEMA; map to closest protocol bucket.
    "title": "header",
    "subtitle": "header",
    "attestation_block": "footer",
    "attestation": "footer",
    # Letter/document structure labels LLMs emit for epistolary documents.
    "heading": "header",
    "address": "header",
    "date_line": "header",
    "salutation": "body",
    "greeting": "body",
    "closing": "body",
    "valediction": "body",
    "signature": "body",
    "full_page": "body",
    "full_text": "body",
    "text": "body",
    # Newspaper / print document structure.
    "headline": "header",
    "subheadline": "header",
    "sub_headline": "header",
    "byline": "body",
    "by_line": "body",
    "dateline": "header",
    "date_line": "header",
    "caption": "footnote",
    "photo_caption": "footnote",
    "image_caption": "footnote",
    "pull_quote": "body",
    "pullquote": "body",
    "drop_cap": "body",
    "column_header": "header",
    "section_header": "header",
    "page_number": "footer",
    "page-number": "footer",
    "folio": "footer",
    "running_head": "header",
    "running_header": "header",
    "colophon": "footer",
    "advertisement": "body",
    "classified": "body",
    "masthead": "header",
    "kicker": "header",
    "deck": "header",
    "attribution": "body",
    "credit": "body",
    "source": "body",
    "subheading": "header",
    "sub_heading": "header",
    "standfirst": "header",
    "lede": "body",
    "lead": "body",
    "paragraph": "body",
    "article": "body",
    "editorial": "body",
    "column": "body",
}
# ISO 15924 script codes → ISO 639-2 language codes for known equivalents.
# The protocol expects language codes; some models emit script codes by mistake.
_LANGUAGE_ALIASES: dict[str, str] = {
    "latn": "lat",
    "latin": "lat",
    "grek": "grc",
    "greek": "grc",
    "cyrl": "rus",
    "arab": "ara",
    "arabic": "ara",
    "hebr": "heb",
    "hans": "zho",
    "hant": "zho",
    "jpan": "jpn",
    # Common vernacular aliases LLMs emit
    "english": "eng",
    "middle_english": "enm",
    "middle english": "enm",
    "old_french": "fro",
    "old french": "fro",
    "anglo-norman": "fro",
    "anglo_norman": "fro",
    "french": "fra",
    "german": "deu",
    "italian": "ita",
    "spanish": "spa",
    "portuguese": "por",
    "dutch": "nld",
}
# Protocol's controlled era vocabulary (matches benchmark/validate_schema.py
# VALID_ERAS). Aliases handle common LLM mistakes (capitalization, slashes,
# verbose phrasings).
_VALID_ERAS = frozenset({
    "medieval", "early_modern", "enlightenment",
    "nineteenth_century", "twentieth_century", "contemporary",
})
_ERA_ALIASES: dict[str, str] = {
    "late_medieval": "medieval",
    "early_medieval": "medieval",
    "high_medieval": "medieval",
    "late_medieval_early_modern": "medieval",  # ambiguous; pick the earlier bucket
    "late_medieval/early_modern": "medieval",
    "renaissance": "early_modern",
    "early_modern_english": "early_modern",
    "19th_century": "nineteenth_century",
    "20th_century": "twentieth_century",
    "21st_century": "contemporary",
    "modern": "contemporary",
}
_VALID_DIPLOMATIC_PROFILES = frozenset({"strict", "semi_strict", "layout_aware", "diplomatic_plus"})
_DIPLOMATIC_PROFILE_ALIASES: dict[str, str] = {
    "academic": "strict",
    "scholarly": "strict",
    "paleographic": "strict",
    "diplomatic": "strict",
    "loose": "layout_aware",
    "semi-strict": "semi_strict",
}
_VALID_NORM_MODES = frozenset({"diplomatic", "normalized"})
_NORM_MODE_ALIASES: dict[str, str] = {
    "unnormalized": "diplomatic",
    "raw": "diplomatic",
    "normalised": "normalized",
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


_MARGIN_DIRECTIONS = (
    ("left",   "margin_left"),
    ("right",  "margin_right"),
    ("top",    "margin_top"),
    ("bottom", "margin_bottom"),
)


def _normalize_position_value(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    s = raw.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = s.replace("-", "_")
    while "__" in s:
        s = s.replace("__", "_")
    s = _POSITION_ALIASES.get(s, s)
    if s in _VALID_POSITION:
        return s
    # Semantic fallback: compound margin/corner strings the model invents.
    # "top_left_margin", "top-right-corner", "bottom_right_margin_note", etc.
    parts = set(s.split("_"))
    if "margin" in parts or "corner" in parts or "marginalia" in parts:
        for kw, pos in _MARGIN_DIRECTIONS:
            if kw in parts:
                return pos
    return raw


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
        # targetEra: canonicalize (lowercase, underscore separators, alias map).
        te = meta.get("targetEra")
        if isinstance(te, str):
            te_norm = te.strip().lower().replace(" ", "_").replace("/", "_")
            while "__" in te_norm:
                te_norm = te_norm.replace("__", "_")
            te_norm = _ERA_ALIASES.get(te_norm, te_norm)
            if te_norm in _VALID_ERAS:
                meta["targetEra"] = te_norm

        # diplomaticProfile and normalizationMode: alias-map common LLM variants.
        # Convert literal "null"/"none" strings to actual None (YAML quirk when
        # the LLM quotes the keyword).
        for _k in ("diplomaticProfile", "normalizationMode", "targetEra", "targetLanguage"):
            _v = meta.get(_k)
            if isinstance(_v, str) and _v.strip().lower() in ("null", "none", "~", ""):
                meta[_k] = None
        dp = meta.get("diplomaticProfile")
        if isinstance(dp, str):
            dp_norm = dp.strip().lower().replace("-", "_")
            dp_norm = _DIPLOMATIC_PROFILE_ALIASES.get(dp_norm, dp_norm)
            if dp_norm in _VALID_DIPLOMATIC_PROFILES:
                meta["diplomaticProfile"] = dp_norm
        nm = meta.get("normalizationMode")
        if isinstance(nm, str):
            nm_norm = nm.strip().lower()
            nm_norm = _NORM_MODE_ALIASES.get(nm_norm, nm_norm)
            if nm_norm in _VALID_NORM_MODES:
                meta["normalizationMode"] = nm_norm

        tl = meta.get("targetLanguage")
        # Map script codes (e.g. "Latn") and English aliases to language codes.
        # Protocol wants "<iso639>-<era>" (e.g. "lat-medieval"), so when the model
        # emits a bare 3-letter code, splice in targetEra if available.
        if isinstance(tl, str):
            tl_norm = tl.strip().lower()
            tl_norm = _LANGUAGE_ALIASES.get(tl_norm, tl_norm)
            if "-" not in tl_norm and tl_norm and tl_norm != "mixed":
                era = meta.get("targetEra")
                if isinstance(era, str) and era.strip():
                    tl_norm = f"{tl_norm}-{era.strip().lower()}"
                elif tl_norm == "lat":
                    # Default Latin docs in this corpus to medieval; the validator
                    # rejects a bare "lat".
                    tl_norm = "lat-medieval"
            meta["targetLanguage"] = tl_norm
            tl = tl_norm
        ehm = meta.get("englishHandwritingModality")
        if isinstance(ehm, str):
            ehm_norm = ehm.strip().lower().replace("-", "_").replace(" ", "_")
            ehm_norm = _ENGLISH_MODALITY_ALIASES.get(ehm_norm, ehm_norm)
            if ehm_norm in _VALID_ENGLISH_MODALITY:
                meta["englishHandwritingModality"] = ehm_norm
        tl_s = tl.strip().lower() if isinstance(tl, str) else ""
        if tl_s and not tl_s.startswith("eng") and tl_s != "mixed":
            meta["englishHandwritingModality"] = None
    is_normalized = meta.get("normalizationMode") == "normalized"
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
        if is_normalized and isinstance(seg.get("text"), str):
            seg["text"] = re.sub(r"=\s*\n", "", seg["text"])


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
