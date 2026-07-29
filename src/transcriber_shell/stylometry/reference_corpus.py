"""Load stylometry-r ``reference_set_medieval_mixed`` chunks for Python Delta."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from transcriber_shell.stylometry.title_genre import GENRES

# Map local genre_signal labels → R / title_genre taxonomy (and reverse).
LOCAL_TO_R: dict[str, str] = {
    "computus_calendar": "computus",
    "astronomical_technical": "astronomy",
    "legal_charter": "legal-writing",
    "liturgical": "sacred-text",
    "theological_scholastic": "scholastic",
    "narrative_history": "history",
    "epistolary": "epistolary",
    "medical_recipe": "medicine",
    "verse_poetry": "poetry",
}

R_TO_LOCAL: dict[str, str] = {v: k for k, v in LOCAL_TO_R.items()}
# Additional R genres fold into the nearest local bucket when needed.
R_TO_LOCAL.update(
    {
        "theology": "theological_scholastic",
        "exegesis": "theological_scholastic",
        "sermon": "theological_scholastic",
        "natural-philosophy": "astronomical_technical",
        "mathematics": "computus_calendar",
        "optics": "astronomical_technical",
        "philosophy": "theological_scholastic",
        "hagiography": "narrative_history",
        "grammar": "theological_scholastic",
        "moral-instruction": "theological_scholastic",
    }
)

_DEFAULT_REF_DIRS = (
    Path(os.environ.get("STYLOMETRY_R_REF", "")).expanduser()
    if os.environ.get("STYLOMETRY_R_REF")
    else None,
    Path.home() / "Projects" / "stylometry-r" / "output" / "de_luce_r_rescore" / "reference_set_medieval_mixed",
    Path("/Users/halxiii/Projects/stylometry-r/output/de_luce_r_rescore/reference_set_medieval_mixed"),
)


def default_reference_dir() -> Path | None:
    for p in _DEFAULT_REF_DIRS:
        if p is None:
            continue
        if p.is_dir():
            return p
    return None


def genre_from_reference_filename(name: str) -> str | None:
    """``astronomy_corpuscorporum_….txt`` → ``astronomy``."""
    stem = Path(name).stem
    for g in sorted(GENRES, key=len, reverse=True):
        if stem == g or stem.startswith(g + "_"):
            return g
    # Fallback: first underscore token if it looks like a genre key.
    head = stem.split("_", 1)[0]
    return head if head in GENRES else None


def load_reference_chunks(
    ref_dir: Path | None = None,
    *,
    max_per_genre: int = 40,
    min_chars: int = 200,
) -> dict[str, list[str]]:
    """Return ``{genre: [chunk_text, …]}`` from a mixed reference directory."""
    root = ref_dir or default_reference_dir()
    if root is None or not root.is_dir():
        return {}
    by_genre: dict[str, list[str]] = defaultdict(list)
    for path in sorted(root.glob("*.txt")):
        genre = genre_from_reference_filename(path.name)
        if not genre:
            continue
        if len(by_genre[genre]) >= max_per_genre:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if len(text) < min_chars:
            continue
        by_genre[genre].append(text)
    return dict(by_genre)


def load_local_label_references(
    ref_dir: Path | None = None,
    **kwargs,
) -> dict[str, list[str]]:
    """Same chunks, keyed by ``genre_signal`` local labels where mappable."""
    raw = load_reference_chunks(ref_dir, **kwargs)
    out: dict[str, list[str]] = defaultdict(list)
    for genre, texts in raw.items():
        local = R_TO_LOCAL.get(genre)
        if not local:
            continue
        out[local].extend(texts)
    return dict(out)
