"""Stylometric analysis for medieval Latin manuscripts.

Book-level fingerprinting for cross-text and cross-codex comparison,
plus genre signal analysis via medieval-proof's trained genre models.
"""

from transcriber_shell.stylometry.fingerprint import (
    BookFingerprint,
    compute_fingerprint,
    compare_fingerprints,
    compare_corpus,
    save_fingerprint,
    load_fingerprint,
)
from transcriber_shell.stylometry.genre_signal import (
    GenreSignal,
    compute_genre_signal,
    save_genre_signal,
    load_genre_signal,
)
from transcriber_shell.stylometry.stylo_delta import (
    burrows_delta_ranking,
    chunk_words,
    rolling_delta_classify,
    rolling_slices,
)
from transcriber_shell.stylometry.title_genre import (
    GENRES,
    GENRE_DISPLAY_LABELS,
    classify_by_title,
    tag_records,
)

__all__ = [
    "BookFingerprint",
    "compute_fingerprint",
    "compare_fingerprints",
    "compare_corpus",
    "save_fingerprint",
    "load_fingerprint",
    "GenreSignal",
    "compute_genre_signal",
    "save_genre_signal",
    "load_genre_signal",
    "burrows_delta_ranking",
    "chunk_words",
    "rolling_delta_classify",
    "rolling_slices",
    "GENRES",
    "GENRE_DISPLAY_LABELS",
    "classify_by_title",
    "tag_records",
]
