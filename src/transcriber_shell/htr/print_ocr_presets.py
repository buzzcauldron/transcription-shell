"""Print OCR presets (historical-ocr print model stacks → Settings updates)."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_ENV_RE = re.compile(r"\$\{(\w+)\}")
_BUILTIN = (
    Path(__file__).resolve().parents[3] / "scripts" / "latin_ms" / "document_types" / "print_ocr_presets.yaml"
)

_SETTINGS_KEYS = frozenset({
    "tesseract_lang",
    "tesseract_psm",
    "htr_preprocess_enabled",
    "htr_preprocess_invert",
    "htr_preprocess_contrast",
    "htr_preprocess_sharpen",
    "htr_preprocess_binarise",
    "tesseract_finetune_lang",
    "tesseract_finetune_path",
})


def _expand_env(val: str) -> str:
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), val)


@lru_cache(maxsize=1)
def _load_raw() -> dict[str, Any]:
    if not _BUILTIN.is_file():
        return {}
    return yaml.safe_load(_BUILTIN.read_text(encoding="utf-8")) or {}


def settings_updates_for_doc_type(doc_type: str | None) -> dict[str, Any]:
    """Return Settings.model_copy(update=…) fields for a document type."""
    if not doc_type:
        return {}
    raw = _load_raw()
    block = (raw.get("doc_types") or {}).get(doc_type)
    if not isinstance(block, dict):
        return {}
    return {k: v for k, v in block.items() if k in _SETTINGS_KEYS}


def resolve_finetune_path() -> Path | None:
    raw = _load_raw()
    finetune = raw.get("finetune") or {}
    for cand in finetune.get("candidates") or []:
        if not isinstance(cand, str):
            continue
        p = Path(_expand_env(cand)).expanduser()
        if p.is_file():
            return p.resolve()
    return None
