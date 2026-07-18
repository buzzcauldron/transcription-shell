#!/usr/bin/env python3
"""
computus_keyword_tagger.py

Score a plain-text Latin transcription against all 18 genres in the
reference corpus, plus computus tradition sub-scores.

Inspired by reasoning-stylometry's style_keyword_tagger.py pattern:
  - disjoint weighted vocabulary sets per genre
  - NFKD normalization + case-folding (handles OCR/diplomatic ligatures)
  - single-word keys via Counter lookup (O(1)), multi-word via substring scan
  - structural density signals alongside keyword signals

Output JSON:
  genre_scores        : {genre: weighted_score, ...}  — all 18 genres
  dominant_genre      : name of highest-scoring genre (null if all zero)
  genre_density       : dominant score / total_words * 1000 (per-mille)
  tradition_scores    : {dionysiac/victorian/bedan/irish: score}  — computus only
  dominant_tradition  : highest-scoring tradition (null if all zero)
  tradition_density   : dominant tradition score / total_words * 1000
  style_scores        : {table_markers/computus_technical: score}
  total_words         : int
  keyword_hits        : [[word, genre, weight], ...]  — top 20

Usage:
    python3 computus_keyword_tagger.py <text_file>
    cat text.txt | python3 computus_keyword_tagger.py
"""

import json
import re
import sys
import unicodedata
from collections import Counter

# ---------------------------------------------------------------------------
# Genre keyword sets  (18 genres matching the reference corpus)
# Keys may be single words OR multi-word phrases (matched via substring).
# Weights: 1=general marker, 2=moderately specific, 3=highly specific, 4=unique
# ---------------------------------------------------------------------------

GENRE_SETS = {
    "astronomy": {
        "stella": 1, "stellae": 1, "planeta": 2, "planetae": 2,
        "sidus": 2, "siderum": 2, "zodiacus": 3, "eclipsis": 3,
        "solstitium": 3, "solstithium": 3, "aequinoctium": 3,
        "sphaera": 2, "astronomia": 4, "astronomicus": 4,
        "constellatio": 3, "astrologus": 3, "horoscop": 3,
        "orbis caelestis": 3, "motus stellarum": 3,
        "planetas": 2, "ascendens": 2, "descendens": 2,
    },
    "computus": {
        "computus": 3, "compotus": 3, "paschalis": 2, "pascha": 2,
        "luna": 2, "lunae": 2, "cycl": 2, "cyclus": 2,
        "annus": 1, "anni": 1, "dies": 1, "hebdomas": 2,
        "embolismus": 4, "saltus": 3, "epacta": 4, "concurrentes": 4,
        "indictio": 3, "kalend": 2, "nisan": 3, "bissextilis": 4,
        "decemnovennalis": 4, "ogdoas": 4, "hendecas": 4,
        "terminus paschalis": 4, "feria": 2,
    },
    "epistolary": {
        "salutem": 3, "salutatem": 2, "dilectissimo": 3, "karissimo": 3,
        "reverentissimo": 3, "reverendissimo": 3, "epistola": 3,
        "epistolae": 3, "littera": 2, "litterae": 2,
        "scribimus": 2, "scripsimus": 2, "legatus": 2, "missus": 1,
        "mandavimus": 2, "humiliter": 2, "supplicamus": 2,
        "in christo": 2, "frater tuus": 2, "pater venerabilis": 2,
    },
    "exegesis": {
        "scriptura": 2, "scripturae": 2, "evangelium": 2,
        "interpretatio": 3, "interpretatur": 3, "significat": 2,
        "figura": 2, "typus": 3, "allegorice": 4, "tropologice": 4,
        "anagoge": 4, "anagogice": 4, "litera": 2, "sensus": 2,
        "prophetia": 2, "mysterium": 3, "secundum litteram": 3,
        "mystice": 3, "id est": 1, "hoc est": 1,
    },
    "grammar": {
        "nomen": 2, "verbum": 2, "participium": 3, "pronomen": 3,
        "adverbium": 3, "praepositio": 3, "coniunctio": 3,
        "nominativus": 4, "genitivus": 4, "dativus": 4,
        "accusativus": 4, "ablativus": 4, "grammatica": 4,
        "donatus": 3, "priscianus": 3, "prisciani": 3,
        "syllaba": 3, "syllabae": 3, "declinatio": 3,
        "casus": 2, "genus": 2, "numerus": 2,
    },
    "hagiography": {
        "sanctus": 2, "sancti": 2, "beatus": 2, "beatae": 2,
        "martyr": 3, "martyris": 3, "confessor": 3,
        "virgo": 3, "virginis": 3, "miraculum": 3, "miracula": 3,
        "vita": 1, "passio": 3, "martyrium": 3,
        "reliquiae": 3, "monasterium": 2, "anachoreta": 3,
        "sanctitate": 3, "venerabilis": 2, "conversatio": 2,
    },
    "history": {
        "annal": 2, "annales": 2, "chronicon": 3, "cronica": 3,
        "rex": 1, "regis": 1, "regnum": 1, "imperator": 2,
        "dux": 2, "ducis": 2, "bellum": 2, "pugna": 2,
        "victoria": 2, "comes": 2, "gesta": 3, "historia": 3,
        "anno domini": 3, "anno regni": 3,
        "exercitus": 2, "obsidio": 3, "tributum": 2,
    },
    "legal-writing": {
        "lex": 2, "legis": 2, "canon": 2, "canonis": 2,
        "decretum": 3, "decreti": 3, "constitutio": 2,
        "placuit": 3, "synodus": 3, "concilium": 3,
        "capitulare": 4, "capitularia": 4, "iustitia": 2,
        "sententia": 2, "iudex": 2, "testis": 2,
        "prohibetur": 2, "anathema": 3, "excommunicatio": 3,
    },
    "mathematics": {
        "numerus": 2, "numeri": 2, "multiplicatio": 4,
        "divisio": 3, "additio": 4, "subtractio": 4,
        "calculus": 3, "proportio": 3, "ratio": 2,
        "geometria": 4, "arithmetica": 4, "quadratum": 3,
        "circulus": 3, "diameter": 4, "triangulus": 4,
        "abacus": 4, "algorismus": 4, "digit": 2,
    },
    "medicine": {
        "medicina": 3, "medicus": 3, "medici": 3,
        "febris": 3, "herba": 2, "herbae": 2,
        "remedium": 3, "potio": 3, "sanguis": 2,
        "calor": 2, "frigus": 2, "humor": 3, "humores": 3,
        "phlegma": 4, "cholera": 3, "melancholia": 4,
        "hippocrates": 4, "galenus": 4, "galeni": 4,
        "anatomia": 4, "dosis": 3,
    },
    "moral-instruction": {
        "virtus": 2, "virtutis": 2, "vitium": 2, "peccatum": 2,
        "humilitas": 3, "superbia": 3, "avaritia": 3,
        "luxuria": 3, "caritas": 2, "castitas": 3,
        "prudentia": 3, "temperantia": 3, "fortitudo": 3,
        "mores": 2, "disciplina": 2, "exemplum": 2,
        "de moribus": 3, "vita bona": 2,
    },
    "natural-philosophy": {
        "natura": 2, "naturae": 2, "elementum": 3, "elementa": 3,
        "ignis": 2, "aqua": 1, "terra": 1, "aer": 2,
        "causa": 2, "effectus": 2, "materia": 2, "forma": 2,
        "qualitas": 3, "quantitas": 3, "substantia": 3,
        "de natura": 3, "rerum natura": 3,
        "physica": 3, "cosmologia": 4, "cosmographia": 4,
    },
    "philosophy": {
        "philosophus": 3, "philosophia": 3, "philosophi": 3,
        "ratio": 2, "intellectus": 3, "anima": 2,
        "bonum": 2, "malum": 2, "veritas": 2, "sapientia": 2,
        "plato": 3, "platonis": 3, "aristoteles": 3,
        "dialectica": 4, "logica": 4, "metaphysica": 4,
        "categoriae": 4, "universale": 3, "particulare": 3,
    },
    "poetry": {
        "versus": 2, "metrum": 3, "metrica": 3,
        "carmen": 3, "carminis": 3, "cantus": 2,
        "hexameter": 4, "pentameter": 4, "dactylus": 4,
        "spondeus": 4, "caesura": 4, "elegia": 3,
        "rithmus": 3, "rhythmus": 3, "oda": 3,
        "poeta": 3, "poetae": 3, "vergilius": 3, "virgilius": 3,
    },
    "sacred-text": {
        "dominus": 1, "deus": 1, "christus": 2, "iesus": 2,
        "spiritus sanctus": 3, "scriptura sacra": 3,
        "psalmus": 3, "psalmi": 3, "evangelium": 2,
        "apostolus": 2, "testamentum": 3, "lex dei": 3,
        "gratia": 2, "gracia": 2, "misericordia": 2,
        "oratio": 2, "liturgia": 3, "officium": 2,
    },
    "scholastic": {
        "quaestio": 4, "quaestiones": 4, "disputatio": 4,
        "articulus": 3, "obiectio": 4, "respondetur": 4,
        "conclusio": 3, "probatur": 3, "demonstratur": 3,
        "syllogismus": 4, "praemissa": 4,
        "universale": 3, "particulare": 3,
        "ad primum": 3, "ad secundum": 3,
    },
    "sermon": {
        "fratres": 2, "carissimi": 2, "dilectissimi": 2,
        "hodie": 2, "praedicare": 3, "praedicator": 3,
        "verbum dei": 3, "sermo": 3, "homilia": 4,
        "audite": 2, "audientes": 2,
        "in nomine": 2, "gloria": 2, "alleluia": 3,
        "evangelium hodie": 3, "lectio": 2,
    },
    "theology": {
        "trinitas": 4, "trinitate": 4, "pater": 1,
        "filius": 1, "spiritus": 1, "deus": 1,
        "incarnatio": 4, "redemptio": 4, "sacramentum": 3,
        "baptismus": 3, "baptismi": 3, "fides": 2,
        "heresis": 4, "haeresis": 4, "haereticus": 4,
        "orthodoxus": 3, "consubstantialis": 4,
        "spiritus sanctus": 3, "de fide": 3,
    },
}

# ---------------------------------------------------------------------------
# Computus tradition sub-scores (within the computus genre)
# ---------------------------------------------------------------------------

TRADITION_SETS = {
    "dionysiac": {
        "dionysius": 3, "dionysii": 3, "decemnovennalis": 4,
        "argumentum": 2, "argumenta": 2, "indictio": 3,
        "epacta": 4, "concurrentes": 4, "nisan": 3, "hebraeus": 2,
        "annus incarnationis": 4, "anno incarnationis": 4,
    },
    "victorian": {
        "victorius": 4, "victorii": 4, "aquitanus": 4, "aquitan": 3,
        "hilarius": 3, "hilarii": 3, "laterculus": 4,
        "supputatio": 3, "cursus annorum": 3,
    },
    "bedan": {
        "beda": 4, "bedae": 4, "venerabilis": 2,
        "de temporum ratione": 5, "temporum ratione": 4,
        "de temporibus": 4, "compotus": 3,
        "rithmus": 3, "rhythmus": 3, "annus domini": 3,
    },
    "irish": {
        "hibernia": 4, "hibernensis": 4, "hibernicus": 4,
        "columbanus": 4, "columbani": 4, "latercus": 4,
        "laterculum": 4, "lxxxiv": 4, "octoginta quattuor": 4,
        "iona": 3,
    },
}

# Structural/scribal style signals
STYLE_SETS = {
    "table_markers": {
        "tabula": 2, "tabulae": 2, "columna": 2, "columnae": 2,
        "ordo": 1, "ordines": 1, "series": 1,
    },
    "computus_technical": {
        "embolismus": 3, "embolismi": 3, "saltus lunae": 4,
        "ogdoas": 4, "hendecas": 4, "bissextilis": 4,
        "epact": 2, "regulares": 2, "claves terminorum": 3,
    },
}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    return unicodedata.normalize("NFKD", text).casefold()


def score_keywords(norm_text: str, word_counts: Counter, kw_set: dict,
                   category: str, hits: list) -> int:
    total = 0
    for key, weight in kw_set.items():
        key_norm = normalize(key)
        if " " in key_norm:
            count = 0
            start = 0
            while True:
                pos = norm_text.find(key_norm, start)
                if pos == -1:
                    break
                count += 1
                start = pos + len(key_norm)
        else:
            count = word_counts.get(key_norm, 0)
        if count > 0:
            weighted = count * weight
            total += weighted
            hits.append((key, category, weight, count, weighted))
    return total


def tag(text: str) -> dict:
    norm_text = normalize(text)
    words = re.findall(r"\w+", norm_text)
    total_words = len(words)
    word_counts = Counter(words)
    hits: list = []

    genre_scores = {}
    for genre, kw_set in GENRE_SETS.items():
        genre_scores[genre] = score_keywords(norm_text, word_counts, kw_set, genre, hits)

    tradition_scores = {}
    for trad, kw_set in TRADITION_SETS.items():
        tradition_scores[trad] = score_keywords(norm_text, word_counts, kw_set, trad, hits)

    style_scores = {}
    for sty, kw_set in STYLE_SETS.items():
        style_scores[sty] = score_keywords(norm_text, word_counts, kw_set, sty, hits)

    def dominant(scores):
        if not any(scores.values()):
            return None
        return max(scores, key=lambda k: scores[k])

    dom_genre = dominant(genre_scores)
    dom_trad = dominant(tradition_scores)

    dom_genre_score = genre_scores[dom_genre] if dom_genre else 0
    dom_trad_score = tradition_scores[dom_trad] if dom_trad else 0

    hits_sorted = sorted(hits, key=lambda h: (h[2], h[4]), reverse=True)[:20]

    return {
        "genre_scores": genre_scores,
        "dominant_genre": dom_genre,
        "genre_density": round(dom_genre_score / total_words * 1000, 4) if total_words else 0.0,
        "tradition_scores": tradition_scores,
        "dominant_tradition": dom_trad,
        "tradition_density": round(dom_trad_score / total_words * 1000, 4) if total_words else 0.0,
        "style_scores": style_scores,
        "total_words": total_words,
        "keyword_hits": [[h[0], h[1], h[2]] for h in hits_sorted],
    }


def main():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()
    print(json.dumps(tag(text), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
