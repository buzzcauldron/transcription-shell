"""Title/author-based genre identification for medieval Latin corpora.

This is the *metadata* counterpart to ``genre_signal`` (which scores genre from
text content). Many corpora we work with -- Corpus Corporum, the CoMMA/CATMuS
manuscript corpora, medieval-proof, latinlibrary dumps -- carry a work title
and/or author (or a ``work_id`` that encodes one). This module maps those
strings onto the expanded medieval-Latin genre taxonomy used across the
stylometry reports, using ordered title-keyword rules plus a medieval-author
map, optionally gated by a year range.

Design goals:
- **Reusable across corpora**: ``classify_by_title`` takes plain strings;
  ``tag_records`` adapts any iterable of dicts via configurable field keys.
- **Conservative**: returns ``None`` when no rule matches, so callers can fall
  back to the content-based scorer (``genre_signal.compute_genre_signal``) or a
  corpus's own label rather than guessing.
- **No heavy dependencies**: pure standard library.

Example
-------
>>> classify_by_title("Iohannis de Sacrobosco Tractatus de sphaera", year=1230)
'astronomy'
>>> classify_by_title("Summa theologiae", author="Thomas de Aquino")
'scholastic'
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Iterator, Optional

# Expanded medieval-Latin genre taxonomy (kept in sync with
# stylometry-r/output/de_luce_r_rescore/genre_taxonomy.json).
GENRES: tuple[str, ...] = (
    "natural-philosophy", "astronomy", "computus", "mathematics", "medicine",
    "optics", "scholastic", "theology", "exegesis", "sermon", "philosophy",
    "hagiography", "history", "epistolary", "poetry", "legal-writing",
    "grammar", "sacred-text", "moral-instruction",
)

GENRE_DISPLAY_LABELS: dict[str, str] = {
    "natural-philosophy": "natural philosophy (physica) / De caelo, De anima / encyclopedic science",
    "astronomy": "astronomy / De sphaera / theorica planetarum",
    "computus": "computus / time-reckoning",
    "mathematics": "mathematics / arithmetic / geometry / music theory",
    "medicine": "medicine / regimen / practica",
    "optics": "optics / perspectiva / theory of light and vision",
    "scholastic": "scholastic quaestiones / summae / sentence commentaries",
    "theology": "theology / doctrinal and dogmatic prose",
    "exegesis": "biblical exegesis / commentary / gloss",
    "sermon": "sermons / homiletics",
    "philosophy": "philosophy / logic / ethics / Boethian consolation",
    "hagiography": "saints' lives / hagiography",
    "history": "chronicle / historiography / gesta / annals",
    "epistolary": "letters / epistolary prose",
    "poetry": "verse / hymns / rhythmical poetry",
    "legal-writing": "canon and civil law / decretals / statutes / charters",
    "grammar": "grammar / artes / etymologies",
    "sacred-text": "liturgy / psalter / scripture",
    "moral-instruction": "mirrors for princes / moral instruction / exempla",
}

# Ordered title-keyword rules; the first genre whose keyword is a substring of
# the folded title wins. Order encodes specificity (narrow scientific genres
# before broad ones; scholastic/exegesis before generic theology).
TITLE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("astronomy", ("de sphera", "de sphaera", "sphera mundi", "astronom", "de astro",
                   "de celo et mundo", "de caelo et mundo", "de stellis", "planetar",
                   "theorica planet")),
    ("computus", ("computus", "de computo", "de compoto", "computo eccles",
                  "de temporum ratione", "de ratione temporum",
                  "de temporibus", "kalendar", "calendar", "massa compoti")),
    ("optics", ("perspectiv", "de iride", "de radiis", "de colore", "de lineis",
                "catoptric", "de speculis", "de multiplicatione specierum")),
    ("mathematics", ("arithmetic", "geometri", "de numeris", "algorism", "algoris",
                     "de proportionibus", "proportion", "musica", "de institutione arithmetic",
                     "elementa geometri", "de ponderibus")),
    ("medicine", ("medicin", "de morbis", "de morbo", "regimen sanitatis", "de urinis",
                  "de pulsibus", "pantegni", "chirurg", "antidotarium", "de febribus",
                  "herbari", "de simplici", "de gradibus", "viaticum", "de egritud",
                  "de aegritud", "de dietis", "de flebotomia")),
    ("natural-philosophy", ("physic", "de natura rerum", "de rerum natura", "de natura",
                            "meteor", "de anima", "de generatione et corrupt", "de mineral",
                            "de vegetabil", "de animalibus", "de plantis", "de proprietatibus rerum",
                            "de elementis", "de sensu", "de motu", "de causis", "philosophia natural",
                            "de fluxu", "de impressionibus", "de luce", "de lumine")),
    ("scholastic", ("summa theolog", "summa contra", "summa de", "quaestio", "questio",
                    "quaestiones", "questiones", "sententiar", "in sententias", "super sententias",
                    "disputat", "quodlib", "de ente et essentia", "itinerarium mentis")),
    ("exegesis", ("commentar", "expositio", "glossa", "glosa", "enarration", "super psalm",
                  "in psalm", "in genesim", "in evangel", "in matth", "in iohann", "in luc",
                  "in epistol", "postilla", "moralia in iob", "hexaemeron", "exameron",
                  "tractatus in", "explanatio")),
    ("sermon", ("sermo", "sermones", "homili", "homel")),
    ("hagiography", ("vita s", "vitae s", "vita sancti", "vita beati", "de vita et", "passio",
                     "legenda", "miracul", "translatio s", "de miraculis", "acta sanctorum")),
    ("history", ("chronic", "cronic", "gesta", "historia", "annal", "de bello", "res gestae",
                 "de gestis", "liber pontificalis", "origo gentis", "de expugnatione",
                 "flores historiarum")),
    ("epistolary", ("epistol", "epistul", "registrum epistolarum")),
    ("poetry", ("carmen", "carmina", "versus", "poema", "hymn", "ecloga", "egloga", "elegi",
                "poetria", "liber carminum")),
    ("legal-writing", ("decret", "leges", "de iure", "constitutio", "capitular", "statut",
                       "regula iuris", "summa iuris", "institutiones iuris", "digest", "codex iuris",
                       "de legibus")),
    ("grammar", ("grammatic", "ars maior", "ars minor", "ars grammatic", "orthograph",
                 "etymolog", "de orthographia", "doctrinale", "graecismus", "de octo partibus")),
    ("theology", ("de trinitate", "de fide", "de deo", "theolog", "de sacrament", "de virtutibus",
                  "de vitiis", "confession", "soliloqu", "de civitate dei", "de doctrina christ",
                  "enchiridion", "de libero arbitrio", "de gratia", "de predestinat",
                  "de contempl", "de sacramentis")),
    ("philosophy", ("de consolatione philosoph", "ethic", "logic", "dialectic", "isagoge",
                    "categorie", "de interpretatione", "topica", "de fato", "de amicitia",
                    "de officiis")),
    ("sacred-text", ("psalteri", "missal", "breviari", "antiphonar", "graduale", "sacramentar",
                     "officium", "hymnari", "biblia", "vulgata", "lectionar")),
    ("moral-instruction", ("speculum", "de moribus", "disciplina", "exempl", "de eruditione",
                           "de regimine principum", "flores", "proverbi", "de contemptu mundi",
                           "liber consolationis")),
)

# Medieval-author overrides, applied when no title rule matches. Names are
# matched as substrings of the lowercased author string.
AUTHOR_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("sacrobosco", "sacro bosco"), "astronomy"),
    (("witelo", "vitellio"), "optics"),
    (("grosseteste", "lincolniensis"), "natural-philosophy"),
    (("roger bacon", "rogerus bacon", "rogerius bacon"), "natural-philosophy"),
    (("albertus magnus",), "natural-philosophy"),
    (("thomas de aquino", "thomas aquinas", "aquinas"), "scholastic"),
    (("bonaventura",), "scholastic"),
    (("duns scotus", "ioannes duns"), "scholastic"),
    (("ockham", "occam"), "scholastic"),
    (("petrus lombardus", "lombardus"), "scholastic"),
    (("abaelard", "abelard"), "scholastic"),
    (("anselmus", "anselm"), "theology"),
    (("beda", "venerabilis beda"), "computus"),
    (("constantinus africanus",), "medicine"),
    (("bernardus claraevall", "bernardus claravall"), "sermon"),
    (("hugo de sancto victore",), "theology"),
)

DEFAULT_MEDIEVAL_YEARS = (500, 1500)


def fold(s: str) -> str:
    """Lowercase and fold ae/oe -> e for tolerant substring matching."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return s.replace("\u00e6", "ae").replace("ae", "e").replace("oe", "e")


def parse_year(raw) -> Optional[int]:
    """Extract a 3-4 digit year from a messy field (e.g. '1236', 'c. 1230')."""
    if raw is None:
        return None
    m = re.search(r"-?\d{3,4}", str(raw))
    if not m:
        return None
    try:
        return int(m.group())
    except ValueError:
        return None


def classify_by_title(
    title: str,
    author: Optional[str] = None,
    year=None,
    *,
    medieval_years: Optional[tuple[int, int]] = None,
) -> Optional[str]:
    """Return an expanded-taxonomy genre for a work, or ``None`` if unmatched.

    Args:
        title: Work title (or a ``work_id``/filename that encodes one).
        author: Optional author string, used as a fallback signal.
        year: Optional year (int or messy string); parsed leniently.
        medieval_years: If given as ``(lo, hi)``, works whose parsed year falls
            outside the range return ``None`` (period gating). If ``None`` (the
            default), no year gating is applied.

    Returns:
        A genre from :data:`GENRES`, or ``None`` when nothing matches.
    """
    if medieval_years is not None:
        y = parse_year(year)
        if y is None or not (medieval_years[0] <= y <= medieval_years[1]):
            return None
    t = fold(title)
    for genre, keys in TITLE_RULES:
        if any(k in t for k in keys):
            return genre
    # Author overrides: match against the author field *and* the title/work_id,
    # since many corpora embed the author in the identifier (e.g.
    # "latinlibrary/bonaventura.itinerarium").
    haystack = f"{author or ''} {title or ''}".lower()
    for names, genre in AUTHOR_MAP:
        if any(n in haystack for n in names):
            return genre
    return None


def tag_records(
    records: Iterable[dict],
    *,
    title_key: str = "title",
    author_key: Optional[str] = "author",
    year_key: Optional[str] = "year",
    genre_key: str = "genre",
    medieval_years: Optional[tuple[int, int]] = None,
    overwrite: bool = False,
    fallback_keys: tuple[str, ...] = ("work_id", "doc_id", "path", "shelfmark"),
) -> Iterator[dict]:
    """Yield records annotated with a title-matched ``genre_key``.

    Works with heterogeneous corpora (Corpus Corporum, CoMMA/CATMuS, medieval-
    proof, latinlibrary). If ``title_key`` is missing/empty, the first present
    ``fallback_keys`` field is used as the title-like string (e.g. ``work_id``).
    Records already carrying a genre are left untouched unless ``overwrite``.
    """
    for rec in records:
        if not overwrite and rec.get(genre_key):
            yield rec
            continue
        title = rec.get(title_key) or ""
        if not title:
            for fk in fallback_keys:
                if rec.get(fk):
                    title = str(rec[fk])
                    break
        author = rec.get(author_key) if author_key else None
        year = rec.get(year_key) if year_key else None
        genre = classify_by_title(title, author, year, medieval_years=medieval_years)
        if genre is not None:
            rec = {**rec, genre_key: genre}
        yield rec


def _main(argv: Optional[list[str]] = None) -> int:
    """CLI: title-tag a JSONL corpus and report / write genre labels.

    Usage:
        python -m transcriber_shell.stylometry.title_genre INPUT.jsonl \
            [--title-key title] [--author-key author] [--year-key year] \
            [--medieval-min 500 --medieval-max 1500] [--out OUTPUT.jsonl] \
            [--overwrite]
    """
    import argparse
    import collections
    import json
    import sys

    ap = argparse.ArgumentParser(description="Title-match genre IDs for a JSONL corpus.")
    ap.add_argument("input", help="JSONL file with one record per line")
    ap.add_argument("--title-key", default="title")
    ap.add_argument("--author-key", default="author")
    ap.add_argument("--year-key", default="year")
    ap.add_argument("--genre-key", default="genre")
    ap.add_argument("--medieval-min", type=int, default=None)
    ap.add_argument("--medieval-max", type=int, default=None)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--out", default=None, help="Write tagged JSONL here (else count only)")
    args = ap.parse_args(argv)

    years = None
    if args.medieval_min is not None and args.medieval_max is not None:
        years = (args.medieval_min, args.medieval_max)

    def read():
        with open(args.input, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    counts: collections.Counter = collections.Counter()
    n = matched = 0
    out_f = open(args.out, "w", encoding="utf-8") if args.out else None
    try:
        for rec in tag_records(
            read(),
            title_key=args.title_key,
            author_key=args.author_key,
            year_key=args.year_key,
            genre_key=args.genre_key,
            medieval_years=years,
            overwrite=args.overwrite,
        ):
            n += 1
            g = rec.get(args.genre_key)
            if g in GENRES:
                matched += 1
            counts[g or "(unmatched)"] += 1
            if out_f:
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    finally:
        if out_f:
            out_f.close()

    print(f"records: {n}  matched: {matched} ({100*matched/max(1,n):.1f}%)", file=sys.stderr)
    for g, c in counts.most_common():
        print(f"{c:8d}  {g}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
