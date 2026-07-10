"""Book-length stylometric fingerprint for cross-text comparison.

Produces a fixed-dimension feature vector from a full text (or a list of
per-page texts). Designed for comparing multiple texts from the same codex
or corpus — e.g. the seven NYPL Sacrobosco texts.

The fingerprint combines:
  - Function word frequency profile (57 canonical Latin function words)
  - Character bigram profile (30 fixed Latin bigrams)
  - Character trigram profile (20 fixed Latin trigrams)
  - Scalar statistics: TTR, hapax rate, mean word length, Heaps β,
    rolling-TTR variance, lexical density

All vector features are L1-normalised so values are comparable across texts
of different lengths. Scalar features are stored raw (unit-different) and
exposed separately in comparisons.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np

# ── canonical function words ──────────────────────────────────────────────────
# v→u, j→i already applied; all lowercase
FUNCTION_WORDS: list[str] = [
    "et", "in", "est", "non", "de", "ad", "per", "ut", "cum", "ex",
    "sed", "uel", "enim", "nam", "ergo", "igitur", "ita", "iam",
    "quod", "que", "qui", "qua", "quo", "ab", "pro", "si", "nisi",
    "sicut", "autem", "tamen", "etiam", "quia", "dum", "ante", "post",
    "sub", "super", "inter", "secundum", "propter", "contra",
    "esse", "sunt", "erat", "fuit", "erit", "hoc", "hec", "hic",
    "ille", "illa", "illud", "ipse", "ipsa", "ipsum",
    "omnis", "omne", "omnium", "omnes",
]

# ── fixed character n-gram vocabularies ──────────────────────────────────────
# Derived from high-frequency sequences in medieval Latin prose.
# Fixed vocab ensures the same feature positions across all texts.
CHAR_BIGRAMS: list[str] = [
    "er", "re", "in", "on", "en", "es", "st", "et", "ti", "is",
    "at", "um", "us", "or", "it", "nt", "ur", "ra", "ro", "al",
    "ar", "li", "an", "ri", "de", "ne", "di", "pr", "te", "ad",
]

CHAR_TRIGRAMS: list[str] = [
    "ent", "unt", "est", "int", "per", "pro", "ter", "ant", "ere", "tur",
    "ium", "tio", "que", "non", "bus", "uis", "ens", "ine", "tra", "ore",
]

_FW_DIM = len(FUNCTION_WORDS)    # 59
_BG_DIM = len(CHAR_BIGRAMS)      # 30
_TG_DIM = len(CHAR_TRIGRAMS)     # 20
VECTOR_DIM = _FW_DIM + _BG_DIM + _TG_DIM  # 109


# ── text normalisation ────────────────────────────────────────────────────────

def _canonicalize(text: str) -> str:
    t = unicodedata.normalize("NFD", text)
    t = "".join(c for c in t if unicodedata.category(c)[0] != "M")
    t = t.lower().replace("v", "u").replace("j", "i")
    t = re.sub(r"['\.\,\;\:\!\?\"`‘’“”…—\-\(\)\[\]⁊ꝙ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tokenize(text: str) -> list[str]:
    return [w for w in _canonicalize(text).split() if w.isalpha() and len(w) >= 2]


def _char_ngrams(tokens: list[str], n: int) -> Counter:
    c: Counter = Counter()
    for tok in tokens:
        for i in range(len(tok) - n + 1):
            c[tok[i:i + n]] += 1
    return c


def _heaps_fit(tokens: list[str]) -> tuple[float, float, float]:
    """Fit V(n) ≈ K·n^β.  Returns (K, β, R²)."""
    if len(tokens) < 20:
        return (1.0, 0.5, 0.0)
    seen: set[str] = set()
    step = max(1, len(tokens) // 500)
    ns, vs = [], []
    for i, tok in enumerate(tokens):
        seen.add(tok)
        if i % step == 0:
            ns.append(i + 1)
            vs.append(len(seen))
    ns.append(len(tokens))
    vs.append(len(seen))
    log_n = np.log(np.array(ns, dtype=float))
    log_v = np.log(np.array(vs, dtype=float))
    beta, log_K = np.polyfit(log_n, log_v, 1)
    K = math.exp(log_K)
    residuals = log_v - (log_K + beta * log_n)
    ss_res = float((residuals ** 2).sum())
    ss_tot = float(((log_v - log_v.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return (round(K, 4), round(float(beta), 4), round(r2, 4))


def _l1_normalize(counts: list[float]) -> list[float]:
    total = sum(counts)
    if total == 0:
        return [0.0] * len(counts)
    return [c / total for c in counts]


# ── fingerprint dataclass ─────────────────────────────────────────────────────

@dataclass
class BookFingerprint:
    """Stylometric fingerprint for a complete text (book / codex section)."""

    doc_id: str
    n_tokens: int
    n_types: int
    n_pages: int

    # Scalar statistics
    ttr: float
    hapax_rate: float
    mean_word_len: float
    heaps_K: float
    heaps_beta: float
    heaps_r2: float
    rolling_ttr_variance: float
    lexical_density: float      # (1 - fw_fraction)

    # Fixed-dim normalised frequency vectors
    fw_profile: list[float]       # 57 dims: fw_count / total_fw_count
    fw_of_corpus: list[float]     # 57 dims: fw_count / total_tokens
    char_bigrams: list[float]     # 30 dims
    char_trigrams: list[float]    # 20 dims

    # Top-word snapshot (not part of distance vector)
    top30_words: list[tuple[str, int]] = field(default_factory=list)

    # Provenance
    source_label: str = ""

    def to_vector(self) -> np.ndarray:
        """Concatenate all normalised frequency vectors into one array (107-d)."""
        return np.array(self.fw_profile + self.char_bigrams + self.char_trigrams, dtype=float)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["top30_words"] = [[w, c] for w, c in self.top30_words]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BookFingerprint":
        d = dict(d)
        d["top30_words"] = [tuple(pair) for pair in d.get("top30_words", [])]
        return cls(**d)


# ── main computation ──────────────────────────────────────────────────────────

def compute_fingerprint(
    pages: Sequence[str],
    doc_id: str,
    *,
    source_label: str = "",
) -> BookFingerprint:
    """Compute a BookFingerprint from a sequence of page texts.

    ``pages`` may be a single-element list containing the entire text, or one
    element per manuscript page — the latter enables rolling-TTR variance.
    """
    # Tokenize per page (needed for rolling TTR variance)
    page_tokens: list[list[str]] = [_tokenize(p) for p in pages]
    all_tokens: list[str] = [tok for pt in page_tokens for tok in pt]

    n = len(all_tokens)
    freq = Counter(all_tokens)
    n_types = len(freq)
    hapax = sum(1 for c in freq.values() if c == 1)

    ttr = n_types / n if n else 0.0
    hapax_rate = hapax / n_types if n_types else 0.0
    mean_word_len = sum(len(t) for t in all_tokens) / n if n else 0.0
    K, beta, r2 = _heaps_fit(all_tokens)

    # Rolling TTR variance across pages
    page_ttrs = [
        (len(set(pt)) / len(pt)) if pt else 0.0
        for pt in page_tokens
    ]
    rolling_ttr_var = float(np.var(page_ttrs)) if len(page_ttrs) > 1 else 0.0

    # Function word features
    fw_counts = [freq.get(fw, 0) for fw in FUNCTION_WORDS]
    fw_total = sum(fw_counts) or 1
    fw_profile = [c / fw_total for c in fw_counts]
    fw_of_corpus = [c / n if n else 0.0 for c in fw_counts]
    lexical_density = 1.0 - (sum(fw_counts) / n) if n else 0.0

    # Character n-gram features
    bg_counts_raw = _char_ngrams(all_tokens, 2)
    tg_counts_raw = _char_ngrams(all_tokens, 3)
    bg_vec = _l1_normalize([bg_counts_raw.get(bg, 0) for bg in CHAR_BIGRAMS])
    tg_vec = _l1_normalize([tg_counts_raw.get(tg, 0) for tg in CHAR_TRIGRAMS])

    top30 = [(w, c) for w, c in freq.most_common(30)]

    return BookFingerprint(
        doc_id=doc_id,
        n_tokens=n,
        n_types=n_types,
        n_pages=len(pages),
        ttr=round(ttr, 6),
        hapax_rate=round(hapax_rate, 6),
        mean_word_len=round(mean_word_len, 4),
        heaps_K=K,
        heaps_beta=beta,
        heaps_r2=r2,
        rolling_ttr_variance=round(rolling_ttr_var, 6),
        lexical_density=round(lexical_density, 6),
        fw_profile=[round(x, 8) for x in fw_profile],
        fw_of_corpus=[round(x, 8) for x in fw_of_corpus],
        char_bigrams=[round(x, 8) for x in bg_vec],
        char_trigrams=[round(x, 8) for x in tg_vec],
        top30_words=top30,
        source_label=source_label,
    )


# ── comparison ────────────────────────────────────────────────────────────────

def compare_fingerprints(fp_a: BookFingerprint, fp_b: BookFingerprint) -> dict:
    """Return a comparison dict between two BookFingerprints.

    Keys:
      vector_cosine      — cosine distance on full 107-d vector
      vector_l1          — L1 (Manhattan) distance on full 107-d vector
      fw_cosine          — cosine distance on function-word profile only
      char_cosine        — cosine distance on char n-gram profile only
      scalar_delta       — per-scalar absolute differences
    """
    def cosine_dist(a: np.ndarray, b: np.ndarray) -> float:
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na < 1e-12 or nb < 1e-12:
            return 1.0
        return float(1.0 - np.dot(a, b) / (na * nb))

    va, vb = fp_a.to_vector(), fp_b.to_vector()
    fw_a = np.array(fp_a.fw_profile)
    fw_b = np.array(fp_b.fw_profile)
    ch_a = np.array(fp_a.char_bigrams + fp_a.char_trigrams)
    ch_b = np.array(fp_b.char_bigrams + fp_b.char_trigrams)

    scalar_keys = [
        "ttr", "hapax_rate", "mean_word_len",
        "heaps_beta", "rolling_ttr_variance", "lexical_density",
    ]
    scalar_delta = {
        k: round(abs(getattr(fp_a, k) - getattr(fp_b, k)), 6)
        for k in scalar_keys
    }

    # Per-function-word profile delta (for interpretability)
    fw_delta = {
        fw: round(abs(fp_a.fw_profile[i] - fp_b.fw_profile[i]), 6)
        for i, fw in enumerate(FUNCTION_WORDS)
    }
    top_fw_delta = sorted(fw_delta.items(), key=lambda x: -x[1])[:10]

    return {
        "doc_a": fp_a.doc_id,
        "doc_b": fp_b.doc_id,
        "vector_cosine": round(cosine_dist(va, vb), 6),
        "vector_l1": round(float(np.abs(va - vb).sum()), 6),
        "fw_cosine": round(cosine_dist(fw_a, fw_b), 6),
        "char_cosine": round(cosine_dist(ch_a, ch_b), 6),
        "scalar_delta": scalar_delta,
        "top_fw_delta": top_fw_delta,
    }


def compare_corpus(fingerprints: list[BookFingerprint]) -> list[dict]:
    """All-pairs comparison across a list of fingerprints."""
    results = []
    for i in range(len(fingerprints)):
        for j in range(i + 1, len(fingerprints)):
            results.append(compare_fingerprints(fingerprints[i], fingerprints[j]))
    results.sort(key=lambda x: x["vector_cosine"])
    return results


# ── I/O ───────────────────────────────────────────────────────────────────────

def save_fingerprint(fp: BookFingerprint, path: str | Path) -> None:
    Path(path).write_text(json.dumps(fp.to_dict(), indent=2, ensure_ascii=False))


def load_fingerprint(path: str | Path) -> BookFingerprint:
    return BookFingerprint.from_dict(json.loads(Path(path).read_text()))
