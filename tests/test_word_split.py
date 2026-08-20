"""Tests for the rules-only word-boundary repair pass.

The bias under test is asymmetric: a missed split is harmless (the draft is
unchanged), a wrong split fabricates words that were never on the page and
corrupts the function-word signal downstream. So most of these assert that
something is NOT split.
"""

from __future__ import annotations

import pytest

from transcriber_shell.repair.word_split import (
    Lexicon,
    fold,
    fold_with_map,
    repair_line,
    repair_lines,
    split_token,
)


@pytest.fixture
def lex() -> Lexicon:
    """Small lexicon standing in for the harvested genre corpus."""
    return Lexicon(
        {
            fold(w): c
            for w, c in {
                "nomine": 40000,
                "opus": 20000,
                "ualde": 8000,
                "diuinis": 6000,
                "ingenii": 3000,
                "mensam": 2500,
                "modio": 900,
                "inde": 30000,
                "itaque": 25000,
                "nonne": 5000,
                # Frequent noise of the kind the real lexicon carries.
                "gu": 9000,
                "rei": 9000,
                "dis": 9000,
                "sonant": 9000,
                "en": 9000,
                "us": 9000,
                "li": 9000,
                "ti": 9000,
            }.items()
        }
    )


def test_fold_index_map_tracks_original_offsets():
    """Folding is not length-preserving; the map must point back into the token."""
    folded, idx = fold_with_map("quaedam")
    assert folded == "quedam"
    assert idx == [0, 1, 2, 4, 5, 6]
    # folded[2] == 'e' is the collapsed 'ae'; it must point at the 'a' that
    # started it, so a cut there slices the original before the ligature.
    assert folded[2] == "e"
    assert "quaedam"[idx[2]] == "a"


def test_fold_strips_abbreviation_marks_and_folds_uv():
    assert fold("domồ") == fold("domo")  # combining mark dropped
    assert fold("ſanctus") == "sanctus"
    assert fold("uult") == fold("vult")


def test_splits_fused_function_word(lex):
    assert split_token("INNOMINE", lex) == ["IN", "NOMINE"]
    assert split_token("adopus", lex) == ["ad", "opus"]
    assert split_token("meualde", lex) == ["me", "ualde"]


def test_split_preserves_original_glyphs_and_case(lex):
    """Output is sliced from the input, so folding cannot modernise the text."""
    assert split_token("indiuinis", lex) == ["in", "diuinis"]
    parts = split_token("INNOMINE", lex)
    assert "".join(parts) == "INNOMINE"


def test_rare_attested_inflection_is_protected(lex):
    """Regression: a real word attested only a few times must survive.

    Latin prefixes are spelled like prepositions (`in-`, `pro-`, `inter-`) and
    inflectional endings like function words (`-is`, `-ne`, `-te`), so an
    unprotected inflected form gets split at a morpheme boundary and FABRICATES
    the function words the downstream classifier counts. An earlier KNOWN_MIN of
    40 let exactly this through on edition text: `communicantis` ->
    `communicant is`, `intermedium` -> `inter medium`, `inscribatur` ->
    `in scribatur`.
    """
    rare = Lexicon(
        dict(lex.freq,
             **{fold(w): 4 for w in ("communicantis", "intermedium",
                                     "inscribatur", "duodecimi")},
             **{fold("communicant"): 9000, fold("medium"): 9000,
                fold("scribatur"): 9000, fold("decimi"): 9000})
    )
    for w in ("communicantis", "intermedium", "inscribatur", "duodecimi"):
        assert split_token(w, rare) is None, w


def test_enclitic_is_not_peeled_off(lex):
    """`superficiemque` is one token as written; splitting it invents a `que`."""
    encl = Lexicon(dict(lex.freq, **{fold("superficiem"): 5000, fold("que"): 90000}))
    assert split_token("superficiemque", encl) is None


def test_known_word_is_never_split(lex):
    """`inde` must not become `in de`, nor `itaque` -> `ita que`."""
    for w in ("inde", "itaque", "nonne"):
        assert split_token(w, lex) is None


def test_rejects_split_with_no_closed_class_fragment(lex):
    """`gurei` -> `gu rei` is two attested fragments and still wrong."""
    assert split_token("gurei", lex) is None


def test_rejects_short_open_class_fragments(lex):
    """A real word chopped into frequent syllables must be refused."""
    assert split_token("dissonantiam", lex) is None
    assert split_token("SALITI", lex) is None


def test_rejects_all_closed_class_three_way_split(lex):
    """`adreme` (from `ad remedium` broken across a line) must survive intact."""
    assert split_token("adreme", lex) is None


def test_repair_line_keeps_punctuation_attached(lex):
    out, n = repair_line("adopus, INNOMINE.", lex)
    assert n == 2
    assert out == "ad opus, IN NOMINE."


def test_repair_line_leaves_unsplittable_text_untouched(lex):
    text = "quia animus dum diuiditur"
    assert repair_line(text, lex) == (text, 0)


def test_repair_lines_counts_lines_and_tokens(lex):
    lines = ["adopus INNOMINE", "quia animus", "meualde"]
    out, changed, tokens = repair_lines(lines, lex)
    assert changed == 2
    assert tokens == 3
    assert out[1] == "quia animus"


def test_empty_and_degenerate_input(lex):
    assert split_token("", lex) is None
    assert split_token("ad", lex) is None
    assert repair_lines([], lex) == ([], 0, 0)


def test_lexicon_from_tsv_sums_and_stoplists(tmp_path):
    a = tmp_path / "a.tsv"
    b = tmp_path / "b.tsv"
    a.write_text("nomine\t100\nthe\t9999\n", encoding="utf-8")
    b.write_text("nomine\t50\nbogus line without tab\n", encoding="utf-8")
    lx = Lexicon.from_tsv(a, b, stoplist=frozenset({"the"}))
    assert lx.count(fold("nomine")) == 150
    assert lx.count("the") == 0
