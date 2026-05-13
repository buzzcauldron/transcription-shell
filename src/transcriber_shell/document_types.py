"""Document-type specification loader.

Replaces best_model.sh. Each spec is a small YAML file under a search directory
(default: the scripts/latin_ms/document_types/ folder adjacent to this package).

Usage:
    spec = load_doc_type("medieval_latin_legal")
    # spec.prompt_path, spec.htr_path, spec.seg_path, spec.provider, spec.model
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# Directories searched in order for <name>.yaml spec files.
_BUILTIN_DIRS: list[Path] = [
    # src/transcriber_shell/document_types.py → parents[2] = repo root
    Path(__file__).resolve().parents[2] / "scripts" / "latin_ms" / "document_types",
]

_ENV_RE = re.compile(r"\$\{(\w+)\}")


def _expand_env(val: str) -> str:
    """Expand ${VAR} tokens using os.environ (missing vars left as-is)."""
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), val)


def _resolve_path(val: str | None) -> Path | None:
    if not val:
        return None
    p = Path(_expand_env(val)).expanduser()
    return p if p.exists() else p  # return even if not yet present


@dataclass
class DocumentTypeSpec:
    name: str
    prompt: str                     # filename (relative to doc_type dir or scripts/)
    primary_provider: str = "anthropic"
    primary_model: str | None = None
    fallback_provider: str | None = None
    fallback_model: str | None = None
    htr_path: Path | None = None
    seg_path: Path | None = None
    language: str = ""
    era: str = ""
    script: str = ""
    notes: str = ""
    _search_dirs: list[Path] = field(default_factory=list, repr=False)

    def prompt_path(self, extra_dirs: list[Path] | None = None) -> Path | None:
        """Resolve the prompt filename to an absolute path."""
        dirs = list(self._search_dirs) + (extra_dirs or [])
        for d in dirs:
            cand = d / self.prompt
            if cand.is_file():
                return cand
            # also try the scripts/latin_ms/ dir itself
            parent = d.parent
            cand2 = parent / self.prompt
            if cand2.is_file():
                return cand2
        return None


_MODEL_ALIASES: dict[str, tuple[str, str]] = {
    # alias → (provider, model_id)
    "claude-sonnet-4":        ("anthropic", "claude-sonnet-4-20250514"),
    "claude-opus-4":          ("anthropic", "claude-opus-4-20250514"),
    "claude-haiku-4":         ("anthropic", "claude-haiku-4-5-20251001"),
    "gemini-2.5-pro":         ("gemini",    "gemini-2.5-pro"),
    "gemini-2.5-flash":       ("gemini",    "gemini-2.5-flash"),
    "gemini-2.0-flash":       ("gemini",    "gemini-2.0-flash"),
    "gpt-4o":                 ("openai",    "gpt-4o"),
}


def _parse_model_ref(ref: str) -> tuple[str, str | None]:
    """Return (provider, model_id) for a model alias or 'provider/model-id' string."""
    ref = ref.strip()
    if ref in _MODEL_ALIASES:
        return _MODEL_ALIASES[ref]
    if "/" in ref:
        provider, _, model_id = ref.partition("/")
        return provider.lower(), model_id or None
    # bare model id — guess provider
    if ref.startswith("claude"):
        return "anthropic", ref
    if ref.startswith("gemini"):
        return "gemini", ref
    if ref.startswith("gpt"):
        return "openai", ref
    return "anthropic", ref


def _load_spec(raw: dict[str, Any], search_dirs: list[Path]) -> DocumentTypeSpec:
    llm = raw.get("llm", {})
    primary_provider, primary_model = _parse_model_ref(llm.get("primary", "claude-sonnet-4"))
    fallback_provider = fallback_model = None
    if fb := llm.get("fallback"):
        fallback_provider, fallback_model = _parse_model_ref(fb)

    htr_raw = raw.get("htr", {})
    seg_raw = raw.get("segmentation", {})

    return DocumentTypeSpec(
        name=raw.get("name", ""),
        prompt=raw.get("prompt", "prompt_latin.yaml"),
        primary_provider=primary_provider,
        primary_model=primary_model,
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
        htr_path=_resolve_path(htr_raw.get("path")),
        seg_path=_resolve_path(seg_raw.get("path")),
        language=raw.get("language", ""),
        era=raw.get("era", ""),
        script=raw.get("script", ""),
        notes=str(raw.get("notes", "")),
        _search_dirs=search_dirs,
    )


def load_doc_type(
    name: str,
    extra_dirs: list[Path] | None = None,
) -> DocumentTypeSpec:
    """Load a document-type spec by name.  Raises KeyError if not found."""
    search = list(_BUILTIN_DIRS) + (extra_dirs or [])
    for d in search:
        cand = d / f"{name}.yaml"
        if cand.is_file():
            raw = yaml.safe_load(cand.read_text(encoding="utf-8"))
            return _load_spec(raw, search)
    raise KeyError(
        f"Document type {name!r} not found in {[str(d) for d in search]}. "
        f"Available: {list_doc_types(extra_dirs)}"
    )


def list_doc_types(extra_dirs: list[Path] | None = None) -> list[str]:
    """Return names of all available document-type specs."""
    search = list(_BUILTIN_DIRS) + (extra_dirs or [])
    names: list[str] = []
    for d in search:
        if d.is_dir():
            names += [p.stem for p in sorted(d.glob("*.yaml"))]
    return names
