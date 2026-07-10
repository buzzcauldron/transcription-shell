"""Small Python port of the useful ``stylometry-r`` workflows.

The local ``stylometry-r`` scripts rely on ``stylo`` with:

* stopword / fixed-feature vectors
* Burrows Delta classification
* genre-controlled reference/test sets
* rolling slices for mixed or co-authored texts

This module implements those mechanics without requiring R.  It is intentionally
generic: callers provide reference texts keyed by class label and a fixed feature
list.  The genre-signal module uses it with Latin genre prototypes; other callers
can use it with real reference corpora.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Sequence


def normalize_tokens(text: str) -> list[str]:
    """Tokenize text for MFW / stopword Delta comparisons."""
    t = unicodedata.normalize("NFD", text)
    t = "".join(c for c in t if unicodedata.category(c)[0] != "M")
    t = t.lower().replace("v", "u").replace("j", "i")
    t = t.replace("q3", "que").replace("qz", "que").replace("qʒ", "que")
    t = t.replace("⁊", " et ").replace("&", " et ")
    return re.findall(r"[a-z]+", t)


def chunk_words(text: str, chunk_words: int = 2000) -> list[str]:
    """Split a text into near-even non-overlapping word chunks.

    Mirrors ``scripts/build_genre_corpus.py::chunk_to_dir`` in stylometry-r.
    """
    words = text.split()
    if not words:
        return []
    n_chunks = max(1, len(words) // chunk_words)
    chunk_size = max(1, len(words) // n_chunks)
    chunks: list[str] = []
    for i in range(n_chunks):
        start = i * chunk_size
        end = (i + 1) * chunk_size if i < n_chunks - 1 else len(words)
        chunks.append(" ".join(words[start:end]))
    return chunks


def rolling_slices(text: str, slice_words: int = 500, overlap: int = 250) -> list[str]:
    """Return overlapping slices, as in stylometry-r rolling classify scripts."""
    words = text.split()
    if not words:
        return []
    step = max(1, slice_words - overlap)
    out: list[str] = []
    i = 0
    while i < len(words):
        chunk = words[i : i + slice_words]
        if len(chunk) < max(80, slice_words // 2) and out:
            break
        if len(chunk) < 20:
            break
        out.append(" ".join(chunk))
        i += step
    return out


def pick_rolling_window(n_words: int) -> tuple[int, int] | None:
    """Port of stylometry-r's short-text rolling-window heuristic."""
    if n_words < 120:
        return None
    if n_words < 500:
        return (max(80, n_words // 3), max(40, n_words // 6))
    if n_words < 1500:
        return (250, 150)
    return (400, 250)


def feature_frequencies(text: str, features: Sequence[str]) -> list[float]:
    """Relative frequencies for a fixed feature list."""
    toks = normalize_tokens(text)
    total = max(1, len(toks))
    counts = Counter(toks)
    return [counts.get(f, 0) / total for f in features]


@dataclass
class DeltaRanking:
    label: str
    distance: float
    nearest_document: str = ""


@dataclass
class RollingDeltaResult:
    predictions: list[str]
    counts: dict[str, int]
    slice_rankings: list[list[DeltaRanking]] = field(default_factory=list)


def _coerce_references(
    references: Mapping[str, str | Sequence[str]],
) -> list[tuple[str, str, str]]:
    docs: list[tuple[str, str, str]] = []
    for label, value in references.items():
        if isinstance(value, str):
            docs.append((label, f"{label}_001", value))
            continue
        for i, text in enumerate(value, 1):
            docs.append((label, f"{label}_{i:03d}", text))
    return docs


def burrows_delta_ranking(
    references: Mapping[str, str | Sequence[str]],
    target_text: str,
    features: Sequence[str],
) -> list[DeltaRanking]:
    """Classify target text by Burrows Delta against labelled references.

    Distances are computed against each reference document/chunk after z-scoring
    feature frequencies by the reference corpus mean and standard deviation.  The
    returned label distance is the mean distance to documents with that label.
    """
    docs = _coerce_references(references)
    if not docs:
        return []

    ref_vecs = [feature_frequencies(text, features) for _, _, text in docs]
    target = feature_frequencies(target_text, features)
    dims = len(features)
    means = [
        sum(vec[i] for vec in ref_vecs) / len(ref_vecs)
        for i in range(dims)
    ]
    stds = []
    for i in range(dims):
        var = sum((vec[i] - means[i]) ** 2 for vec in ref_vecs) / len(ref_vecs)
        stds.append(math.sqrt(var) or 1e-6)

    def z(vec: Sequence[float]) -> list[float]:
        return [(vec[i] - means[i]) / stds[i] for i in range(dims)]

    z_target = z(target)
    per_doc: list[tuple[str, str, float]] = []
    for (label, doc_id, _text), vec in zip(docs, ref_vecs):
        z_ref = z(vec)
        dist = sum(abs(z_target[i] - z_ref[i]) for i in range(dims)) / max(1, dims)
        per_doc.append((label, doc_id, dist))

    labels = sorted({label for label, _, _ in per_doc})
    rankings: list[DeltaRanking] = []
    for label in labels:
        rows = [(doc_id, dist) for lab, doc_id, dist in per_doc if lab == label]
        mean_dist = sum(dist for _, dist in rows) / len(rows)
        nearest = min(rows, key=lambda x: x[1])[0]
        rankings.append(DeltaRanking(label, mean_dist, nearest))
    rankings.sort(key=lambda r: r.distance)
    return rankings


def rolling_delta_classify(
    references: Mapping[str, str | Sequence[str]],
    target_text: str,
    features: Sequence[str],
    *,
    slice_words: int | None = None,
    overlap: int | None = None,
) -> RollingDeltaResult:
    """Run Delta classification over rolling target slices."""
    n_words = len(target_text.split())
    if slice_words is None or overlap is None:
        picked = pick_rolling_window(n_words)
        if picked is None:
            rankings = burrows_delta_ranking(references, target_text, features)
            pred = rankings[0].label if rankings else ""
            return RollingDeltaResult(
                predictions=[pred] if pred else [],
                counts={pred: 1} if pred else {},
                slice_rankings=[rankings],
            )
        slice_words, overlap = picked

    rankings_by_slice: list[list[DeltaRanking]] = []
    predictions: list[str] = []
    for text_slice in rolling_slices(target_text, slice_words, overlap):
        ranking = burrows_delta_ranking(references, text_slice, features)
        rankings_by_slice.append(ranking)
        if ranking:
            predictions.append(ranking[0].label)
    counts = dict(Counter(predictions).most_common())
    return RollingDeltaResult(predictions, counts, rankings_by_slice)
