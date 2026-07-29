"""Evidence-bearing genre signals for medieval and early printed Latin texts.

This module borrows the useful shape of the sibling ``stylometry-r`` workflows:
compare like with like, prefer function/stop-word style signals where possible,
and classify over chunks instead of trusting a single whole-document label.

If a ``medieval-proof`` genre model is installed, ``compute_genre_signal`` can
still use it.  Otherwise it falls back to a self-contained scorer tuned for the
genres that matter in this project: computus/calendar tables, astronomical
technical material, legal/charter formulae, liturgy, theology/scholastic prose,
narrative/history, epistolary prose, medicine/recipes, and verse.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from transcriber_shell.stylometry.stylo_delta import (
    burrows_delta_ranking,
    rolling_delta_classify,
)

# ── optional medieval-proof integration ──────────────────────────────────────

_env_src = os.environ.get("MEDIEVAL_PROOF_SRC", "").strip()
_MPROOF_SRC = (
    Path(_env_src).expanduser()
    if _env_src
    else Path(__file__).parents[4] / "medieval-proof" / "src"
)

if _MPROOF_SRC.exists() and str(_MPROOF_SRC) not in sys.path:
    sys.path.insert(0, str(_MPROOF_SRC))

try:
    from medieval_proof.features import FeatureSchema, vectorize  # type: ignore
    from medieval_proof.model import load_model  # type: ignore
    from medieval_proof.surprisal import (  # type: ignore
        find_boundaries,
        load_genre_lms,
        score_segments,
    )

    _AVAILABLE = True
    _IMPORT_ERROR = ""
except ImportError as _e:  # pragma: no cover - depends on optional sibling repo
    _AVAILABLE = False
    _IMPORT_ERROR = str(_e)

_DEFAULT_MODEL = (
    Path(__file__).parents[4]
    / "medieval-proof"
    / "data"
    / "models"
    / "genre_medieval.json"
)


# ── genre lexicon ────────────────────────────────────────────────────────────

GENRES: tuple[str, ...] = (
    "computus_calendar",
    "astronomical_technical",
    "legal_charter",
    "liturgical",
    "theological_scholastic",
    "narrative_history",
    "epistolary",
    "medical_recipe",
    "verse_poetry",
)

GENRE_TERMS: dict[str, dict[str, float]] = {
    "computus_calendar": {
        "kal": 2.4,
        "kalendas": 2.4,
        "kalendis": 2.2,
        "non": 1.5,
        "nonas": 2.0,
        "idus": 2.2,
        "epacta": 2.7,
        "aureus": 2.1,
        "numerus": 1.5,
        "littera": 1.2,
        "dominicalis": 2.8,
        "concurrentes": 2.8,
        "septuagesima": 2.7,
        "quadragesima": 2.6,
        "pascha": 2.7,
        "rogationes": 2.6,
        "pentecostes": 2.5,
        "adventus": 1.9,
        "ianuarius": 1.2,
        "februarius": 1.2,
        "martius": 1.2,
        "aprilis": 1.2,
        "maius": 1.2,
        "iunius": 1.2,
        "iulius": 1.2,
        "augustus": 1.2,
        "september": 1.2,
        "october": 1.2,
        "november": 1.2,
        "december": 1.2,
    },
    "astronomical_technical": {
        "sol": 2.1,
        "solis": 2.2,
        "luna": 2.1,
        "lune": 2.1,
        "latitudo": 2.5,
        "longitudo": 2.5,
        "oppositio": 2.4,
        "oppositiones": 2.4,
        "gradus": 2.1,
        "minuta": 1.8,
        "zodiacus": 2.4,
        "aries": 1.8,
        "taurus": 1.8,
        "gemini": 1.8,
        "cancer": 1.8,
        "leo": 1.8,
        "virgo": 1.8,
        "libra": 1.8,
        "scorpio": 1.8,
        "sagittarius": 1.8,
        "capricornus": 1.8,
        "aquarius": 1.8,
        "pisces": 1.8,
        "astrolabium": 2.7,
        "horarium": 2.7,
        "quadratum": 2.2,
        "meridies": 2.0,
        "scala": 1.8,
        "signa": 1.5,
    },
    "legal_charter": {
        "noverint": 3.0,
        "universi": 2.3,
        "sciant": 2.4,
        "sciatis": 2.4,
        "concessi": 2.8,
        "concessimus": 2.8,
        "donavi": 2.7,
        "confirmavi": 2.7,
        "carta": 2.5,
        "cartam": 2.5,
        "sigillum": 2.6,
        "sigilli": 2.4,
        "testibus": 2.4,
        "testes": 2.1,
        "datum": 2.0,
        "anno": 1.2,
        "domini": 1.0,
        "tenendum": 2.4,
        "habendum": 2.4,
        "heredibus": 2.2,
        "imperpetuum": 2.7,
        "presentibus": 1.8,
        "futuris": 1.8,
    },
    "liturgical": {
        "missa": 2.8,
        "officium": 2.7,
        "antiphona": 3.0,
        "responsorium": 3.0,
        "collecta": 2.7,
        "lectio": 2.2,
        "evangelium": 2.3,
        "feria": 2.2,
        "dominica": 1.9,
        "sancti": 1.7,
        "sancta": 1.7,
        "sanctus": 1.7,
        "matutinum": 2.6,
        "vesperae": 2.6,
        "alleluia": 2.8,
        "introitus": 2.7,
        "graduale": 2.7,
        "sequentia": 2.5,
    },
    "theological_scholastic": {
        "quaestio": 3.0,
        "questio": 3.0,
        "utrum": 2.8,
        "videtur": 2.8,
        "respondeo": 3.0,
        "dicendum": 2.7,
        "articulus": 2.6,
        "obiectio": 2.8,
        "contra": 1.7,
        "ergo": 1.8,
        "quia": 1.4,
        "anima": 1.8,
        "deus": 1.4,
        "divinus": 1.8,
        "peccatum": 1.9,
        "gratia": 1.8,
        "auctoritas": 1.9,
        "sententia": 1.8,
    },
    "narrative_history": {
        "rex": 2.2,
        "regis": 1.9,
        "regnum": 1.9,
        "civitas": 2.0,
        "urbs": 1.8,
        "bellum": 2.1,
        "exercitus": 2.1,
        "postea": 2.4,
        "deinde": 2.4,
        "tunc": 1.8,
        "dixit": 2.0,
        "venit": 1.5,
        "obiit": 2.0,
        "natus": 1.8,
        "factum": 1.4,
        "tempore": 1.4,
        "chronica": 2.6,
    },
    "epistolary": {
        "salutem": 3.0,
        "dilecto": 2.8,
        "carissime": 2.9,
        "karissime": 2.9,
        "litteras": 2.6,
        "littere": 2.2,
        "scripsi": 2.7,
        "scribo": 2.5,
        "rescribere": 2.5,
        "vale": 2.8,
        "valete": 2.8,
        "amicus": 1.9,
        "vester": 1.7,
        "vestra": 1.7,
    },
    "medical_recipe": {
        "recipe": 3.2,
        "rec": 2.5,
        "drachma": 2.8,
        "uncia": 2.5,
        "pulvis": 2.2,
        "unguentum": 2.6,
        "emplastrum": 2.6,
        "aqua": 1.5,
        "oleum": 2.1,
        "herba": 2.0,
        "radix": 2.0,
        "febris": 2.3,
        "sanguis": 2.0,
        "dolor": 1.9,
        "coque": 2.3,
        "misce": 2.4,
        "bibere": 2.0,
    },
    "verse_poetry": {
        "versus": 2.4,
        "metrum": 2.2,
        "carmen": 2.6,
        "cantus": 1.8,
        "musa": 2.0,
        "aureus": 1.2,
        "liber": 0.8,
    },
}

MONTH_ABBREVIATIONS = {
    "ian",
    "jan",
    "feb",
    "mar",
    "apr",
    "mai",
    "iun",
    "jun",
    "iul",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
}

LATIN_DELTA_FEATURES: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            "et",
            "in",
            "est",
            "non",
            "de",
            "ad",
            "per",
            "ut",
            "cum",
            "ex",
            "sed",
            "uel",
            "enim",
            "nam",
            "ergo",
            "igitur",
            "quia",
            "quod",
            "qui",
            "que",
            "ab",
            "pro",
            "si",
            "ante",
            "post",
            "sub",
            "super",
            "inter",
            "esse",
            "sunt",
            "hoc",
            "hec",
            "hic",
            "ille",
            "ipse",
            "omnis",
            *[term for terms in GENRE_TERMS.values() for term in terms],
            *MONTH_ABBREVIATIONS,
        ]
    )
)


# ── dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class GenreEvidence:
    """A single interpretable contribution to a genre score."""

    genre: str
    feature: str
    value: float
    weight: float
    contribution: float
    matches: list[str] = field(default_factory=list)


@dataclass
class GenreSignal:
    """Genre classification output for a manuscript text."""

    doc_id: str
    model_name: str
    top_genre: str
    top_prob: float
    genre_probs: dict[str, float]
    genre_surprisal: dict[str, float]
    segment_scores: list[dict]
    boundary_indices: list[int] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    confidence: float = 0.0

    @property
    def ordered_genres(self) -> list[tuple[str, float]]:
        """Genre probability distribution sorted descending."""
        return sorted(self.genre_probs.items(), key=lambda x: -x[1])

    @property
    def surprisal_ranking(self) -> list[tuple[str, float]]:
        """Genres sorted by surprisal ascending (best-fit first)."""
        return sorted(self.genre_surprisal.items(), key=lambda x: x[1])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GenreSignal":
        return cls(**d)


# ── normalisation and segmentation ───────────────────────────────────────────

def _canonicalize(text: str) -> str:
    t = unicodedata.normalize("NFD", text)
    t = "".join(c for c in t if unicodedata.category(c)[0] != "M")
    t = t.lower().replace("v", "u").replace("j", "i")
    # Normalize common diplomatic abbreviation representations into searchable
    # Latin-ish forms without pretending to fully expand the text.
    t = t.replace("q3", "que").replace("qz", "que").replace("qʒ", "que")
    t = t.replace("⁊", " et ").replace("&", " et ")
    t = t.replace("dñi", "domini").replace("dñicam", "dominicam")
    t = re.sub(r"[<>]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", _canonicalize(text))


def _split_segments(pages: Sequence[str], granularity: str) -> list[str]:
    raw_pages = [p.strip() for p in pages if p and p.strip()]
    if granularity == "page":
        return raw_pages
    full = "\n\n".join(raw_pages)
    if granularity == "sentence":
        parts = re.split(r"(?<=[.!?;])\s+", full)
        return [p.strip() for p in parts if len(p.split()) >= 4]
    # Paragraph is the default, but tables often arrive as line blocks; keep
    # medium-sized newline chunks so rolling genre evidence can see table pages.
    paras = [p.strip() for p in re.split(r"\n\s*\n", full) if p.strip()]
    if len(paras) <= 1:
        lines = [ln.strip() for ln in full.splitlines() if ln.strip()]
        return ["\n".join(lines[i : i + 12]) for i in range(0, len(lines), 12)]
    return paras


def _softmax(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    mx = max(scores.values())
    exps = {g: math.exp(v - mx) for g, v in scores.items()}
    total = sum(exps.values()) or 1.0
    return {g: exps[g] / total for g in scores}


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ── stylometry-r style Delta references ──────────────────────────────────────

def _genre_reference_texts() -> dict[str, list[str]]:
    """Corpus-backed refs when available; else compact genre prototypes.

    Prefer stylometry-r ``reference_set_medieval_mixed`` chunks (mapped onto local
    labels). Synthetic term bags remain a last resort when the corpus is absent.
    """
    try:
        from transcriber_shell.stylometry.reference_corpus import load_local_label_references

        corpus = load_local_label_references(max_per_genre=30)
        if corpus:
            return corpus
    except Exception:
        pass

    refs: dict[str, list[str]] = {}
    for genre, terms in GENRE_TERMS.items():
        words: list[str] = []
        for term, weight in terms.items():
            words.extend([term] * max(1, int(round(weight * 3))))
        if genre == "computus_calendar":
            words.extend(
                "kal non idus aureus numerus littera dominicalis epacta "
                "ian feb mar apr mai iun iul aug sep oct nov dec".split()
                * 6
            )
        elif genre == "astronomical_technical":
            words.extend(
                "sol luna signa gradus minuta latitudo longitudo oppositio "
                "scala meridies horarium quadratum".split()
                * 5
            )
        elif genre == "legal_charter":
            words.extend(
                "noverint universi presentes futuri concessi carta sigillum "
                "testibus datum tenendum habendum heredibus imperpetuum".split()
                * 5
            )
        elif genre == "theological_scholastic":
            words.extend("utrum videtur sed contra respondeo dicendum quia ergo".split() * 6)
        refs[genre] = [" ".join(words)]
    return refs


def _delta_evidence(text: str) -> tuple[dict[str, float], list[GenreEvidence], dict[str, Any]]:
    ranking = burrows_delta_ranking(_genre_reference_texts(), text, LATIN_DELTA_FEATURES)
    if not ranking:
        return {g: 0.0 for g in GENRES}, [], {}

    delta_probs = _softmax({row.label: -row.distance for row in ranking})
    scores = {g: delta_probs.get(g, 0.0) * 2.0 for g in GENRES}
    top = ranking[0]
    second = ranking[1] if len(ranking) > 1 else None
    margin = (second.distance - top.distance) if second else top.distance
    evidence = [
        GenreEvidence(
            genre=top.label,
            feature="stylometry_r_delta_nearest",
            value=round(top.distance, 6),
            weight=2.0,
            contribution=round(delta_probs[top.label] * 2.0, 6),
            matches=[
                f"nearest={top.nearest_document}",
                f"margin={margin:.6f}",
            ],
        )
    ]
    summary = {
        "ranking": [
            {
                "genre": row.label,
                "distance": round(row.distance, 6),
                "nearest_document": row.nearest_document,
            }
            for row in ranking[:5]
        ],
        "probabilities": {g: round(p, 6) for g, p in delta_probs.items()},
    }
    return scores, evidence, summary


# ── feature scoring ──────────────────────────────────────────────────────────

def _term_evidence(text: str, toks: list[str]) -> tuple[dict[str, float], list[GenreEvidence]]:
    counts = Counter(toks)
    n = max(1, len(toks))
    scores = {g: 0.0 for g in GENRES}
    evidence: list[GenreEvidence] = []

    for genre, terms in GENRE_TERMS.items():
        matched: list[str] = []
        contribution = 0.0
        for term, weight in terms.items():
            c = counts.get(term, 0)
            if not c:
                continue
            matched.append(term)
            # Saturate repeated formulae so a table full of "kal" is strong
            # evidence but does not swamp every structural signal.
            contribution += weight * (1.0 + math.log(c))
        if contribution:
            scaled = contribution / math.sqrt(n / 80)
            scores[genre] += scaled
            evidence.append(
                GenreEvidence(
                    genre=genre,
                    feature="lexical_markers",
                    value=round(contribution, 4),
                    weight=1.0,
                    contribution=round(scaled, 4),
                    matches=matched[:18],
                )
            )

    return scores, evidence


def _structural_evidence(text: str, toks: list[str]) -> tuple[dict[str, float], list[GenreEvidence]]:
    scores = {g: 0.0 for g in GENRES}
    evidence: list[GenreEvidence] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    line_count = max(1, len(lines))
    token_count = max(1, len(toks))
    pipe_lines = sum(1 for ln in lines if ln.count("|") >= 3)
    digit_tokens = len(re.findall(r"\b\d+\b", text))
    month_abbr = sum(1 for tok in toks if tok[:3] in MONTH_ABBREVIATIONS)
    avg_line_len = sum(len(ln.split()) for ln in lines) / line_count
    short_line_fraction = sum(1 for ln in lines if 3 <= len(ln.split()) <= 9) / line_count
    formula_starters = len(re.findall(r"\b(noverint|sciant|sciatis|datum|testibus)\b", _canonicalize(text)))
    question_markers = len(re.findall(r"\b(utrum|videtur|respondeo|dicendum)\b", _canonicalize(text)))

    def add(genre: str, feature: str, value: float, weight: float) -> None:
        if value <= 0:
            return
        contribution = value * weight
        scores[genre] += contribution
        evidence.append(
            GenreEvidence(
                genre=genre,
                feature=feature,
                value=round(value, 4),
                weight=weight,
                contribution=round(contribution, 4),
            )
        )

    table_density = pipe_lines / line_count
    digit_density = digit_tokens / token_count
    month_density = month_abbr / token_count

    add("computus_calendar", "table_pipe_density", _clip01(table_density * 2.0), 4.0)
    add("computus_calendar", "calendar_month_density", _clip01(month_density * 80.0), 3.2)
    add("computus_calendar", "numeric_table_density", _clip01(digit_density * 18.0), 2.8)
    add("astronomical_technical", "numeric_table_density", _clip01(digit_density * 12.0), 1.8)
    add("astronomical_technical", "diagram_or_table_layout", _clip01(table_density * 1.4), 1.3)
    add("legal_charter", "charter_formula_starters", _clip01(formula_starters / 3), 3.8)
    add("theological_scholastic", "scholastic_question_markers", _clip01(question_markers / 4), 3.5)
    add("verse_poetry", "short_regular_lines", short_line_fraction if line_count >= 6 else 0.0, 2.4)
    add("verse_poetry", "low_average_line_length", _clip01((10 - avg_line_len) / 8), 1.2)

    return scores, evidence


def _score_text(text: str) -> tuple[dict[str, float], list[GenreEvidence]]:
    toks = _tokens(text)
    term_scores, term_evidence = _term_evidence(text, toks)
    struct_scores, struct_evidence = _structural_evidence(text, toks)
    delta_scores, delta_evidence, _delta_summary = _delta_evidence(text)
    scores = {
        g: term_scores[g] + struct_scores[g] + delta_scores[g]
        for g in GENRES
    }

    # Light priors keep zero-evidence genres available but very low.
    for g in scores:
        scores[g] += 0.05
    return scores, term_evidence + struct_evidence + delta_evidence


def _segment_score(text: str) -> dict[str, Any]:
    scores, evidence = _score_text(text)
    probs = _softmax(scores)
    top = max(probs, key=probs.__getitem__)
    ordered = sorted(probs.items(), key=lambda x: -x[1])
    return {
        "text": text[:160],
        "best_genre": top,
        "best_prob": round(probs[top], 6),
        "genre_probs": {g: round(p, 6) for g, p in ordered[:5]},
        "top_evidence": [
            asdict(ev)
            for ev in sorted(evidence, key=lambda ev: -ev.contribution)[:5]
        ],
    }


def _fallback_boundaries(segment_scores: list[dict], window: int, min_delta: float) -> list[int]:
    if len(segment_scores) < 2:
        return []
    boundaries: list[int] = []
    for i in range(1, len(segment_scores)):
        adjacent_prev = segment_scores[i - 1]
        adjacent_cur = segment_scores[i]
        if adjacent_prev["best_genre"] != adjacent_cur["best_genre"]:
            adjacent_strength = min(
                adjacent_prev.get("best_prob", 0.0),
                adjacent_cur.get("best_prob", 0.0),
            )
            if adjacent_strength >= max(0.01, min_delta):
                boundaries.append(i)
                continue

        prev = segment_scores[max(0, i - window) : i]
        cur = segment_scores[i : i + window]
        if not prev or not cur:
            continue
        prev_top = Counter(seg["best_genre"] for seg in prev).most_common(1)[0][0]
        cur_top = Counter(seg["best_genre"] for seg in cur).most_common(1)[0][0]
        if prev_top == cur_top:
            continue
        prev_prob = sum(seg["genre_probs"].get(prev_top, 0.0) for seg in prev) / len(prev)
        cur_prob = sum(seg["genre_probs"].get(cur_top, 0.0) for seg in cur) / len(cur)
        if abs(cur_prob - prev_prob) >= min_delta:
            boundaries.append(i)
    return boundaries


def _compute_fallback_signal(
    pages: Sequence[str],
    doc_id: str,
    *,
    granularity: str,
    boundary_window: int,
    boundary_min_delta: float,
) -> GenreSignal:
    full_text = "\n\n".join(p for p in pages if p and p.strip())
    scores, evidence = _score_text(full_text)
    probs = _softmax(scores)
    ordered = sorted(probs.items(), key=lambda x: -x[1])
    top_genre, top_prob = ordered[0]
    second_prob = ordered[1][1] if len(ordered) > 1 else 0.0

    segments = _split_segments(pages, granularity)
    segment_scores = [_segment_score(seg) for seg in segments]
    boundaries = _fallback_boundaries(segment_scores, boundary_window, boundary_min_delta)

    # Use inverse score as a surrogate ranking so callers that expect
    # ``surprisal_ranking`` still get a meaningful lower-is-better order.
    max_score = max(scores.values()) if scores else 0.0
    genre_surprisal = {
        g: round(max_score - score, 6)
        for g, score in sorted(scores.items(), key=lambda x: x[0])
    }
    evidence_dicts = [
        asdict(ev)
        for ev in sorted(evidence, key=lambda ev: -ev.contribution)[:40]
    ]

    rolling = rolling_delta_classify(
        _genre_reference_texts(),
        full_text,
        LATIN_DELTA_FEATURES,
    )
    if rolling.counts:
        majority, count = next(iter(rolling.counts.items()))
        vote_share = round(count / max(1, len(rolling.predictions)), 6)
        rolling_evidence = asdict(
            GenreEvidence(
                genre=majority,
                feature=(
                    "stylometry_r_rolling_delta_votes"
                    if majority == top_genre
                    else "stylometry_r_rolling_delta_disagreement"
                ),
                value=float(count),
                weight=1.0,
                contribution=vote_share if majority == top_genre else 0.0,
                matches=[f"{label}={n}" for label, n in rolling.counts.items()],
            )
        )
        if majority == top_genre:
            evidence_dicts.insert(0, rolling_evidence)
        else:
            evidence_dicts.append(rolling_evidence)
    confidence = _clip01((top_prob - second_prob) * 1.8 + min(len(evidence_dicts), 12) / 30)

    return GenreSignal(
        doc_id=doc_id,
        model_name="rule_delta_genre_v1",
        top_genre=top_genre,
        top_prob=round(top_prob, 6),
        genre_probs={g: round(p, 6) for g, p in ordered},
        genre_surprisal=genre_surprisal,
        segment_scores=segment_scores,
        boundary_indices=boundaries,
        evidence=evidence_dicts,
        confidence=round(confidence, 6),
    )


# ── external model path ──────────────────────────────────────────────────────

def _compute_medieval_proof_signal(
    pages: Sequence[str],
    doc_id: str,
    *,
    model_path: Path | str | None,
    granularity: str,
    boundary_window: int,
    boundary_min_delta: float,
) -> GenreSignal:
    if not _AVAILABLE:
        raise ImportError(
            f"medieval-proof not found at {_MPROOF_SRC}. "
            f"Set MEDIEVAL_PROOF_SRC=/path/to/medieval-proof/src or install it. "
            f"Original error: {_IMPORT_ERROR}"
        )

    mp = Path(model_path) if model_path else _DEFAULT_MODEL
    lm_path = mp.parent / (mp.stem + ".lm.json")

    if not mp.exists():
        raise FileNotFoundError(f"Genre model not found: {mp}")
    if not lm_path.exists():
        raise FileNotFoundError(f"Genre LMs not found: {lm_path}")

    calibrator = load_model(mp)
    lms = load_genre_lms(lm_path)
    schema = FeatureSchema(ngram_vocab=calibrator.metadata["ngram_vocab"])
    full_text = "\n\n".join(p for p in pages if p.strip())

    vec = vectorize(full_text, schema)
    probs = calibrator.predict_proba(vec)
    genre_probs = {g: round(float(p), 6) for g, p in zip(calibrator.classes, probs)}
    top_genre = max(genre_probs, key=genre_probs.__getitem__)
    genre_surprisal = {g: round(lm.surprisal(full_text), 6) for g, lm in lms.items()}

    scored = score_segments(full_text, lms, granularity)
    for seg in scored:
        seg["text"] = seg["text"][:120]
    boundaries = find_boundaries(scored, window=boundary_window, min_delta=boundary_min_delta)

    ordered = sorted(genre_probs.values(), reverse=True)
    margin = ordered[0] - ordered[1] if len(ordered) > 1 else ordered[0]
    return GenreSignal(
        doc_id=doc_id,
        model_name=mp.stem,
        top_genre=top_genre,
        top_prob=round(genre_probs[top_genre], 6),
        genre_probs=genre_probs,
        genre_surprisal=genre_surprisal,
        segment_scores=scored,
        boundary_indices=boundaries,
        confidence=round(_clip01(margin * 1.5), 6),
    )


# ── public API ───────────────────────────────────────────────────────────────

def compute_genre_signal(
    pages: Sequence[str],
    doc_id: str,
    *,
    model_path: Path | str | None = None,
    granularity: str = "paragraph",
    boundary_window: int = 5,
    boundary_min_delta: float = 0.08,
    prefer_external: bool = True,
    require_external: bool = False,
) -> GenreSignal:
    """Score a manuscript text for genre evidence.

    Args:
        pages: Per-page strings, or a single-element list with the full text.
        doc_id: Identifier stored in the result.
        model_path: Optional medieval-proof calibrator path.
        granularity: Segment granularity ("paragraph", "sentence", or "page").
        boundary_window: Window size for rolling genre-shift detection.
        boundary_min_delta: Minimum probability delta to declare a boundary.
        prefer_external: Use medieval-proof when available; otherwise fall back.
        require_external: Raise if medieval-proof is unavailable or missing.
    """
    if granularity not in {"paragraph", "sentence", "page"}:
        raise ValueError("granularity must be one of: paragraph, sentence, page")

    if prefer_external or require_external:
        try:
            return _compute_medieval_proof_signal(
                pages,
                doc_id,
                model_path=model_path,
                granularity=granularity,
                boundary_window=boundary_window,
                boundary_min_delta=boundary_min_delta,
            )
        except (ImportError, FileNotFoundError):
            if require_external:
                raise

    return _compute_fallback_signal(
        pages,
        doc_id,
        granularity=granularity,
        boundary_window=boundary_window,
        boundary_min_delta=boundary_min_delta,
    )


def save_genre_signal(gs: GenreSignal, path: str | Path) -> None:
    Path(path).write_text(json.dumps(gs.to_dict(), indent=2, ensure_ascii=False))


def load_genre_signal(path: str | Path) -> GenreSignal:
    return GenreSignal.from_dict(json.loads(Path(path).read_text()))
