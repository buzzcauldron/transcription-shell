"""Rules-only word-boundary repair for HTR drafts.

WHY THIS EXISTS
---------------
Measuring the LLM correction pass on 20 manuscript pages showed it rewrote
~75% of lines, and inspection showed the overwhelming majority of those edits
were *word-boundary* repairs, not character recognition fixes:

    INNOMINE      ->  IN NOMINE
    utluceat      ->  ut luceat
    dignatiestis  ->  dignati estis
    tribustuis    ->  tribus tuis

That is dictionary segmentation. It needs a Latin word list and dynamic
programming, not a language model. Running it before the LLM removes the
majority of the diff the LLM would otherwise have to emit, and for the
stylometry consumer -- which only needs function words back -- it may remove
the need for the LLM call entirely.

APPROACH
--------
For each whitespace token that is NOT a known word, search for the segmentation
into known words that maximises summed log-frequency minus a per-split penalty.
Accept it only if every fragment clears a frequency floor.

The conservative bias is deliberate and asymmetric on purpose: a missed split
leaves the draft as it was, but a wrong split *invents* two words that were
never on the page and corrupts the exact function-word signal the downstream
stylometry measures. Every threshold here is set to prefer doing nothing.
"""

from __future__ import annotations

import gzip
import math
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# ATTESTATION: a token seen even a few times in the corpus is a real word and is
# never split. Deliberately far lower than the fragment floors below, because the
# two thresholds answer different questions -- "is this already a word?" wants
# maximum coverage, "may this be a fragment?" wants strong evidence.
#
# Set to 40 initially, which was a bug with teeth: Latin is heavily inflected, so
# `communicantis`, `intermedium`, `inscribatur`, `duodecimi` each fall below 40
# even in a 60M-word corpus, and with them unprotected the pass split them at
# prefix/ending boundaries -- `communicant is`, `inter medium`, `in scribatur`.
# Latin prefixes are spelled like prepositions and endings like function words,
# so those splits do not merely damage the text, they FABRICATE the exact
# function words the downstream classifier counts.
KNOWN_MIN = 3
# Frequency floor for an open-class fragment, by fragment length. Short
# fragments need far more evidence than long ones.
#
# WHY LENGTH-DEPENDENT: the lexicon is built from harvested text and carries a
# long tail of 2-3 character OCR fragments with respectable counts -- `gu`,
# `nd`, `rp`, `ce` all clear a flat floor of 60. With a flat floor the DP
# happily produced `INNOMINE` -> `INN O MIN E` and `agitamur` -> `a git a mur`,
# because enough junk bigrams were "legal" that a many-piece path outscored the
# right two-piece one. Latin short words are a small CLOSED set, so short
# fragments are gated on membership in that set instead of on frequency.
FRAG_MIN_LONG = 120      # len >= 5
FRAG_MIN_MED = 400       # len 4
FRAG_MIN_SHORT = 4000    # len 3, and only when not in SHORT_WORDS
# Cost charged per split, in log-frequency units. Set above log(FRAG_MIN_LONG)
# so an extra piece must earn more than a merely-attested word's worth of
# evidence; this is what keeps the DP from shredding a token into legal noise.
SPLIT_PENALTY = 13.0
MAX_PARTS = 3
MIN_FRAG_LEN = 2
# Enclitics. `superficiemque` -> `superficiem que` is a real editorial
# convention, but it is not error repair: the token was never mis-spaced, and
# splitting it invents a function-word token where the scribe wrote one word.
# Refused so the function-word rate reflects the text rather than our tokenizer.
ENCLITICS = frozenset({"que", "ne", "ue", "ve", "ce"})

# Latin words of one or two letters, plus the three-letter closed-class items
# that carry most run-together boundaries. This is an allowlist, not a
# frequency test: `in`, `ad`, `ut` are legitimate fragments and `gu`, `nd`,
# `rp` are not, and no corpus count separates them reliably.
SHORT_WORDS = frozenset("""
a ab ad an at aut c cum d de e et ex g h i in me ne nec non o ob per pro que
qui quo re se si sub te tu ub uel ut
ac ait ante apud aput auem circa contra coram cuius cur dum eo ea eos eis eius
enim erga ergo est esse et etiam extra haec hanc hic his hinc hoc hos huc iam
id idem ideo ille illa illo inde infra inter intra ipse ipsa ipso is ita iuxta
nam nisi nobis nos nunc omnis penes post prae praeter prope propter quae quam
quia quid quod quos sed seu sic sicut sine sit siue sui suis sunt super supra
tam tamen trans tunc uel ubi unde usque uos
fit sit dat dic fac ait rex res lex die dei deo dni dns uir uis duo tres
""".split())

# Every fragment that is NOT closed-class must be at least this long. Combined
# with the FRAG_MIN_* floors this is what finally stopped the shredding: the
# corpus contains enough frequent 2-3 character noise (`gu`, `en`, `us`, `dis`)
# that a frequency floor alone cannot tell a word from a syllable, but real
# open-class Latin words are essentially all four characters or more.
OPEN_MIN_LEN = 4
# Three-letter and shorter fragments not in SHORT_WORDS are held to
# FRAG_MIN_SHORT; one-letter fragments are refused outright. `a`/`e`/`o` are
# real Latin words but as FRAGMENTS they are overwhelmingly the tail of a
# misread word, and admitting them is what produced `INN O MIN E`.

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Single-character substitutions applied during folding. Each maps one input
# character to exactly one output character so the index map stays 1:1 for them.
_ONE_TO_ONE = {"\u017f": "s", "j": "i", "v": "u", "\u0131": "i"}
# Characters that expand or contract, handled explicitly in the fold loop.
_TO_E = {"\u00e6", "\u0153"}  # ae, oe ligatures -- and ae/oe fold to e anyway


def fold_with_map(tok: str) -> tuple[str, list[int]]:
    """Fold ``tok`` for lexicon lookup and report where each folded char came from.

    Medieval scribes do not distinguish u/v or i/j, spell ``ae``/``oe`` as ``e``,
    and HTR output carries abbreviation diacritics the lexicon never has. Folding
    affects LOOKUP ONLY.

    The index map is what makes that safe. Folding is not length-preserving
    (``ae`` -> ``e``, a combining mark -> nothing), so a cut position in folded
    space is not a cut position in ``tok``. ``idx[k]`` is the offset in ``tok``
    where folded character ``k`` began, which lets the caller slice the original
    token -- keeping the scribe's own glyphs and capitalisation -- at a boundary
    it found in folded space. Returning only the folded string would force the
    caller to either rebuild from folded text (modernising the transcription) or
    skip every token whose length changed (i.e. most abbreviated ones).
    """
    d = unicodedata.normalize("NFD", tok)
    out: list[str] = []
    idx: list[int] = []
    i = 0
    n = len(d)
    while i < n:
        ch = d[i]
        low = ch.lower()
        if 0x300 <= ord(ch) <= 0x36F:  # combining mark: drop
            i += 1
            continue
        if low in _TO_E:
            out.append("e")
            idx.append(i)
            i += 1
            continue
        # ae / oe -> e, consuming two input characters for one folded one.
        if low in ("a", "o") and i + 1 < n and d[i + 1].lower() == "e":
            out.append("e")
            idx.append(i)
            i += 2
            continue
        out.append(_ONE_TO_ONE.get(low, low))
        idx.append(i)
        i += 1
    return "".join(out), idx


def fold(tok: str) -> str:
    """Folded lookup key for ``tok`` (see :func:`fold_with_map`)."""
    return fold_with_map(tok)[0]


@dataclass
class Lexicon:
    """Folded word -> frequency, with the folding applied at build time."""

    freq: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_tsv(cls, *paths: str | Path, stoplist: frozenset[str] = frozenset()) -> "Lexicon":
        """Load one or more ``word<TAB>count`` files, summing counts.

        Multiple files are additive so a ground-truth lexicon (diplomatic forms,
        correctly segmented by hand) can be stacked on an edition lexicon
        (broad vocabulary coverage) without either one dominating.
        """
        freq: dict[str, int] = {}
        for path in paths:
            p = Path(path)
            if not p.exists():
                continue
            opener = gzip.open if p.suffix == ".gz" else open
            with opener(p, "rt", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("#"):
                        continue
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) != 2:
                        continue
                    w, c = parts[0].strip().lower(), parts[1].strip()
                    if not w or not c.isdigit():
                        continue
                    if w in stoplist:
                        continue
                    k = fold(w)
                    if k:
                        freq[k] = freq.get(k, 0) + int(c)
        return cls(freq)

    def count(self, key: str) -> int:
        return self.freq.get(key, 0)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self.freq)


def _legal_fragment(frag: str, lex: Lexicon) -> int:
    """Frequency-derived score for ``frag`` if it may stand alone, else 0.

    Gate depends on length, because short Latin words are a closed set while
    long ones are open-class. See the FRAG_MIN_* commentary above.
    """
    n = len(frag)
    if n < MIN_FRAG_LEN:
        return 0
    if frag in SHORT_WORDS:
        # A closed-class word is legal regardless of its count in this corpus,
        # but still scores by frequency so the DP can prefer the likelier one.
        return max(lex.count(frag), FRAG_MIN_LONG)
    if n <= 3:
        floor = FRAG_MIN_SHORT
    elif n == 4:
        floor = FRAG_MIN_MED
    else:
        floor = FRAG_MIN_LONG
    c = lex.count(frag)
    return c if c >= floor else 0


def split_token(tok: str, lex: Lexicon) -> list[str] | None:
    """Best legal segmentation of ``tok``, or None to leave it alone.

    Returns fragments sliced out of the ORIGINAL token, so diacritics and
    capitalisation survive; only the lookup went through :func:`fold`.
    """
    key, idx = fold_with_map(tok)
    if len(key) < 2 * MIN_FRAG_LEN:
        return None
    # Already a word: never split. Checked on the folded key so `INNOMINE` and
    # `innomine` behave identically.
    if lex.count(key) >= KNOWN_MIN:
        return None

    n = len(key)
    # best[i] = (score, parts_count, cut_index) for key[:i]
    NEG = -1e18
    best: list[tuple[float, int, int]] = [(NEG, 0, -1)] * (n + 1)
    best[0] = (0.0, 0, -1)
    for i in range(1, n + 1):
        for j in range(0, i):
            prev_score, prev_parts, _ = best[j]
            if prev_score == NEG:
                continue
            if prev_parts >= MAX_PARTS:
                continue
            c = _legal_fragment(key[j:i], lex)
            if not c:
                continue
            score = prev_score + math.log(c) - (SPLIT_PENALTY if j > 0 else 0.0)
            if score > best[i][0]:
                best[i] = (score, prev_parts + 1, j)

    score, parts, _ = best[n]
    if score == NEG or parts < 2:
        return None

    # Walk the cuts back through folded space, then translate each cut to an
    # offset in the original token via the index map.
    cuts: list[int] = []
    i = n
    while i > 0:
        j = best[i][2]
        cuts.append(j)
        i = j
    cuts.reverse()
    bounds = [idx[c] for c in cuts] + [len(tok)]
    parts_out = [tok[a:b] for a, b in zip(bounds, bounds[1:]) if b > a]
    # A fold that collapsed characters can put two cuts on the same original
    # offset, which would emit an empty or duplicated fragment. Reject rather
    # than guess.
    if len(parts_out) != len(cuts):
        return None

    folded_parts = [fold(p) for p in parts_out]
    # An open-class fragment must be long enough to be a word, not a syllable.
    if any(fp not in SHORT_WORDS and len(fp) < OPEN_MIN_LEN for fp in folded_parts):
        return None
    # At least one fragment must be closed-class.
    #
    # WHY: the error this pass exists to fix is a function word fused to its
    # neighbour (`ad`+`opus`, `et`+`hoc`, `in`+`nomine`, `unde`+`fit`) -- that is
    # what the HTR loses and what the stylometry needs back. A candidate split
    # where no fragment is closed-class is far more often a real word being
    # broken into syllables (`gurei`, `SALITI`, `dissonantiam`) than a genuine
    # missing space, so refusing those trades a few real fixes for not
    # fabricating words that were never on the page.
    if not any(fp in SHORT_WORDS for fp in folded_parts):
        return None
    # A three-piece split made entirely of closed-class words is almost always
    # a long word chopped at coincidental function-word boundaries
    # (`adreme` -> `ad re me`, from `ad remedium` broken across a line), so
    # require a content word to anchor it.
    if len(folded_parts) >= 3 and all(fp in SHORT_WORDS for fp in folded_parts):
        return None
    # Peeling an enclitic off the end is tokenization, not repair -- at any
    # number of parts. Checking only two-part splits let `positionesque` ->
    # `posit iones que` and `demittanturque` -> `de mittantur que` through.
    if folded_parts[-1] in ENCLITICS:
        return None
    return parts_out


def repair_line(line: str, lex: Lexicon) -> tuple[str, int]:
    """Split run-together words in one line. Returns (line, n_tokens_split)."""
    out: list[str] = []
    n_split = 0
    # Split on whitespace but keep punctuation attached to its token, then
    # strip it for lookup and put it back -- `INNOMINE,` must still be seen as
    # `INNOMINE`.
    for chunk in line.split(" "):
        m = _WORD_RE.search(chunk)
        if not m:
            out.append(chunk)
            continue
        pre, core, post = chunk[: m.start()], m.group(0), chunk[m.end() :]
        parts = split_token(core, lex)
        if parts and len(parts) > 1:
            out.append(pre + " ".join(parts) + post)
            n_split += 1
        else:
            out.append(chunk)
    return " ".join(out), n_split


def repair_lines(lines: list[str], lex: Lexicon) -> tuple[list[str], int, int]:
    """Repair every line. Returns (lines, lines_changed, tokens_split)."""
    out: list[str] = []
    changed = tokens = 0
    for ln in lines:
        new, n = repair_line(ln, lex)
        if n:
            changed += 1
            tokens += n
        out.append(new)
    return out, changed, tokens


# ---------------------------------------------------------------------------
# Default lexicon

_DEFAULT_NAME = "latin_lexicon.tsv.gz"
_cached: Lexicon | None = None


def default_lexicon_path() -> Path | None:
    """Locate the shipped lexicon, or None if it is not installed.

    Checked in order: an explicit ``TSHELL_LATIN_LEXICON`` override, the
    package's own ``data/`` directory (installed case), then ``data/`` at the
    repo root (working-tree case).
    """
    env = os.environ.get("TSHELL_LATIN_LEXICON")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    here = Path(__file__).resolve()
    for cand in (
        here.parent / "data" / _DEFAULT_NAME,
        here.parents[3] / "data" / _DEFAULT_NAME,
    ):
        if cand.exists():
            return cand
    return None


def load_default_lexicon() -> Lexicon | None:
    """Load and cache the shipped lexicon; None when unavailable.

    Returning None rather than raising is deliberate: word-boundary repair is an
    optimisation, and a deployment without the data file should fall through to
    the unrepaired draft rather than fail the transcription.
    """
    global _cached
    if _cached is not None:
        return _cached
    path = default_lexicon_path()
    if path is None:
        return None
    _cached = Lexicon.from_tsv(path)
    return _cached
