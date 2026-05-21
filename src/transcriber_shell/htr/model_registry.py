"""Model registry for HTR + segmentation checkpoints.

Reads ``scripts/latin_ms/document_types/models/*.yaml``, each describing a
trained model (path on disk, languages covered, era, script, training round,
metrics). The selector picks the best match for a given doc-type or for an
explicit (language, era, script) tuple.

This replaces hardcoded per-doc-type model paths and lets us add new tuned
models (e.g. an early-modern Latin specialist trained on the 3080) without
editing every doc-type spec — just drop a new YAML in ``models/``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal

import yaml


ModelKind = Literal["htr", "segmentation"]

_ENV_RE = re.compile(r"\$\{(\w+)\}")


def _expand_env(val: str) -> str:
    """Expand ``${VAR}`` tokens using os.environ; leave unmatched as-is."""
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), val)


def _default_registry_dir() -> Path:
    """``scripts/latin_ms/document_types/models/`` relative to the package.

    From this file (``src/transcriber_shell/htr/model_registry.py``):
      parents[0] = src/transcriber_shell/htr/
      parents[1] = src/transcriber_shell/
      parents[2] = src/
      parents[3] = repo root
    """
    return (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "latin_ms"
        / "document_types"
        / "models"
    )


@dataclass
class ModelSpec:
    name: str
    kind: ModelKind
    path: Path
    size_mb: float = 0.0
    languages: list[str] = field(default_factory=list)
    eras: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    era_range: str = ""
    training: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    notes: str = ""
    source_path: Path | None = field(default=None, repr=False)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def round(self) -> int:
        r = self.training.get("round")
        try:
            return int(r)
        except (TypeError, ValueError):
            return 0

    @property
    def best_cer(self) -> float | None:
        """Lowest CER known for this model across reported metrics."""
        m = self.metrics
        candidates: list[float] = []
        v = m.get("val_cer")
        if isinstance(v, (int, float)):
            candidates.append(float(v))
        pc = m.get("per_corpus_cer")
        if isinstance(pc, dict):
            for x in pc.values():
                if isinstance(x, (int, float)):
                    candidates.append(float(x))
        return min(candidates) if candidates else None

    def covers(
        self,
        *,
        language: str | None = None,
        era: str | None = None,
        script: str | None = None,
    ) -> bool:
        """True when all supplied criteria match (``None`` skips the check).

        A ``*`` entry in any field on the spec is a wildcard match (used by the
        segmentation models that are largely script-agnostic).
        """
        def _ok(needle: str | None, haystack: list[str]) -> bool:
            if needle is None or not haystack:
                return True
            if "*" in haystack:
                return True
            return needle in haystack

        return (
            _ok(language, self.languages)
            and _ok(era, self.eras)
            and _ok(script, self.scripts)
        )


def _coerce_list(v: object) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x]
    return []


def _parse_spec(raw: dict, source_path: Path) -> ModelSpec | None:
    """Build a ModelSpec from a parsed YAML dict; return None if required fields missing."""
    name = raw.get("name")
    kind = raw.get("kind")
    path = raw.get("path")
    if not (name and kind and path) or kind not in ("htr", "segmentation"):
        return None
    return ModelSpec(
        name=str(name),
        kind=kind,
        path=Path(_expand_env(str(path))).expanduser(),
        size_mb=float(raw.get("size_mb") or 0.0),
        languages=_coerce_list(raw.get("languages")),
        eras=_coerce_list(raw.get("eras")),
        scripts=_coerce_list(raw.get("scripts")),
        era_range=str(raw.get("era_range") or ""),
        training=dict(raw.get("training") or {}),
        metrics=dict(raw.get("metrics") or {}),
        notes=str(raw.get("notes") or ""),
        source_path=source_path,
    )


def load_all(registry_dir: Path | None = None) -> list[ModelSpec]:
    """Load every model spec under ``registry_dir`` (default: built-in models/)."""
    base = registry_dir or _default_registry_dir()
    if not base.is_dir():
        return []
    out: list[ModelSpec] = []
    for yml in sorted(base.glob("*.yaml")):
        try:
            raw = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(raw, dict):
            continue
        spec = _parse_spec(raw, yml)
        if spec is not None:
            out.append(spec)
    return out


def by_name(name: str, registry_dir: Path | None = None) -> ModelSpec | None:
    """Look up a spec by its ``name:`` field. Returns None if not found."""
    for s in load_all(registry_dir):
        if s.name == name:
            return s
    return None


def _score(
    spec: ModelSpec,
    *,
    language: str | None,
    era: str | None,
    script: str | None,
) -> tuple[int, int, int, int, float]:
    """Sort key for ranking candidates.

    Higher is better, except the final CER which is lower-better; we invert
    it so the whole tuple can be max'd.

    Ordering: (covers_all, language_match, era_match, training_round, -best_cer).
    """
    covers_all = int(spec.covers(language=language, era=era, script=script))
    lang_match = int(language is None or (language in spec.languages or "*" in spec.languages))
    era_match = int(era is None or (era in spec.eras or "*" in spec.eras))
    cer = spec.best_cer if spec.best_cer is not None else 1.0
    return (covers_all, lang_match, era_match, spec.round, -cer)


def select(
    *,
    kind: ModelKind,
    language: str | None = None,
    era: str | None = None,
    script: str | None = None,
    registry_dir: Path | None = None,
    require_exists: bool = True,
) -> ModelSpec | None:
    """Pick the best-fitting model of ``kind`` for the given criteria.

    Filters by kind first, then by criteria (covers() must be true), then by
    the ranking tuple. ``require_exists=True`` (default) drops candidates whose
    .mlmodel file isn't on disk yet — useful so a placeholder spec doesn't
    accidentally win.
    """
    cands = [s for s in load_all(registry_dir) if s.kind == kind]
    if require_exists:
        cands = [s for s in cands if s.exists]
    cands = [s for s in cands if s.covers(language=language, era=era, script=script)]
    if not cands:
        return None
    cands.sort(key=lambda s: _score(s, language=language, era=era, script=script), reverse=True)
    return cands[0]


def candidates(
    *,
    kind: ModelKind | None = None,
    language: str | None = None,
    era: str | None = None,
    script: str | None = None,
    registry_dir: Path | None = None,
) -> list[ModelSpec]:
    """Return every spec matching the criteria, ranked best-first."""
    out = load_all(registry_dir)
    if kind is not None:
        out = [s for s in out if s.kind == kind]
    out = [s for s in out if s.covers(language=language, era=era, script=script)]
    out.sort(key=lambda s: _score(s, language=language, era=era, script=script), reverse=True)
    return out


def format_table(specs: Iterable[ModelSpec]) -> str:
    """Plain-text table for the CLI ``list-htr-models`` command."""
    rows = list(specs)
    if not rows:
        return "(no models found)\n"
    headers = ("name", "kind", "round", "languages", "eras", "exists", "best_cer", "path")
    lines = []
    width = {h: len(h) for h in headers}
    formatted: list[tuple[str, ...]] = []
    for s in rows:
        cer = s.best_cer
        formatted.append(
            (
                s.name,
                s.kind,
                str(s.round),
                ",".join(s.languages) or "—",
                ",".join(s.eras) or "—",
                "yes" if s.exists else "no",
                f"{cer:.4f}" if cer is not None else "—",
                str(s.path),
            )
        )
        for h, v in zip(headers, formatted[-1]):
            width[h] = max(width[h], len(v))
    fmt = "  ".join(f"{{:{width[h]}}}" for h in headers)
    lines.append(fmt.format(*headers))
    lines.append(fmt.format(*("-" * width[h] for h in headers)))
    for row in formatted:
        lines.append(fmt.format(*row))
    return "\n".join(lines) + "\n"
