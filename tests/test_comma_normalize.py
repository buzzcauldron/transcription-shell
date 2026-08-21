"""CoMMA ByT5 normalization helper (mocked — no HF download in CI).

The previous version of this file patched ``_load_pipeline``, which the module
has not had for some time; the patch raised AttributeError and the whole file
counted as one red test that nobody could act on. These patch ``_load_model``,
the function that actually exists, and cover the batching contract.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from transcriber_shell.comma import normalize as N


@pytest.fixture(autouse=True)
def _clear_model_cache():
    """_load_model is lru_cached; a stale entry would leak between tests."""
    N._load_model.cache_clear()
    yield
    N._load_model.cache_clear()


def _fake_model(outputs: list[str]):
    """Return a (tokenizer, model, device) triple mimicking the real loader."""
    tokenizer = MagicMock()
    # The real tokenizer returns a BatchEncoding supporting .to(device) and **.
    enc = MagicMock()
    enc.to.return_value = enc
    enc.keys.return_value = ["input_ids"]
    enc.__iter__ = lambda self: iter(["input_ids"])
    enc.__getitem__ = lambda self, k: "TENSOR"
    tokenizer.return_value = enc
    tokenizer.decode.return_value = outputs[0] if outputs else ""
    tokenizer.batch_decode.return_value = outputs

    model = MagicMock()
    model.generate.return_value = [[0]] * len(outputs)
    return tokenizer, model, "cpu"


def test_normalize_medieval_text_mock() -> None:
    triple = _fake_model(["scribo uobis, non Pauli uel Donati"])
    with patch.object(N, "_load_model", return_value=triple):
        out = N.normalize_medieval_text("Scͥbo uobiᷤᷤ ñ pauli ł donati.")
    assert "scribo" in out
    triple[1].generate.assert_called_once()


def test_normalize_empty_returns_empty() -> None:
    assert N.normalize_medieval_text("") == ""
    assert N.normalize_medieval_text("   ") == ""


def test_normalize_lines_batches_one_generate_call() -> None:
    """Four lines must cost ONE generate(), not four.

    This is the regression the old loop-per-line implementation would fail: it
    issued a generate() per line, ~350k for the corpus.
    """
    triple = _fake_model(["a", "b", "c", "d"])
    with patch.object(N, "_load_model", return_value=triple):
        out = N.normalize_lines(["x", "y", "z", "w"], batch_size=16)
    assert out == ["a", "b", "c", "d"]
    assert triple[1].generate.call_count == 1


def test_normalize_lines_respects_batch_size() -> None:
    triple = _fake_model(["a", "b"])
    with patch.object(N, "_load_model", return_value=triple):
        N.normalize_lines(["x", "y", "z", "w"], batch_size=2)
    assert triple[1].generate.call_count == 2


def test_normalize_lines_keeps_blank_positions_aligned() -> None:
    """Blank lines must not enter the batch but must hold their index.

    Line indices are load-bearing: PageXML and the stylometry export both key on
    position, so dropping or shifting a line corrupts downstream alignment.
    """
    triple = _fake_model(["A", "B"])
    with patch.object(N, "_load_model", return_value=triple):
        out = N.normalize_lines(["first", "   ", "", "second"])
    assert out == ["A", "", "", "B"]
    # Only the two non-blank lines were tokenized.
    sent = triple[0].call_args[0][0]
    assert len(sent) == 2


def test_normalize_lines_empty_input_makes_no_calls() -> None:
    triple = _fake_model([])
    with patch.object(N, "_load_model", return_value=triple):
        assert N.normalize_lines([]) == []
    triple[1].generate.assert_not_called()


def test_normalize_lines_falls_back_to_input_on_empty_output() -> None:
    """An empty generation must not silently delete the line.

    The fake decoder is keyed on the INPUT rather than on position, because
    normalize_lines buckets by length before batching; a positional fake would
    assert against whatever order the bucketing happened to produce instead of
    against the fallback behaviour under test.
    """
    replies = {"keepme": "", "other": "ok"}

    tokenizer, model, device = _fake_model(["placeholder"])
    seen: list[list[str]] = []

    def _tok(texts, **_kw):
        seen.append(list(texts) if isinstance(texts, list) else [texts])
        enc = MagicMock()
        enc.to.return_value = enc
        enc.keys.return_value = ["input_ids"]
        enc.__iter__ = lambda self: iter(["input_ids"])
        enc.__getitem__ = lambda self, k: "TENSOR"
        return enc

    tokenizer.side_effect = _tok
    tokenizer.batch_decode.side_effect = lambda *_a, **_k: [
        replies[t] for t in seen[-1]
    ]

    with patch.object(N, "_load_model", return_value=(tokenizer, model, device)):
        out = N.normalize_lines(["keepme", "other"])
    assert out == ["keepme", "ok"]


# ── segmentation for long text ───────────────────────────────────────────────
#
# ByT5 is byte-level and line-trained. Handed a whole 400-word manifest chunk it
# returned a correctly-normalized first fragment and silently dropped the rest --
# measured at 256 output chars for 200/200 chunks, a ~90% loss that looked like
# success because the surviving text was clean. These cover the segmentation that
# prevents it.


def test_segment_respects_byte_budget() -> None:
    text = " ".join(f"verbum{i}" for i in range(200))
    segs = N.segment_for_byt5(text, target_bytes=200)
    assert len(segs) > 1
    assert all(len(s.encode("utf-8")) <= 200 for s in segs), [
        len(s.encode("utf-8")) for s in segs
    ]


def test_segment_never_splits_mid_word() -> None:
    """A half word would be normalized into a different word."""
    words = [f"w{i:04d}" for i in range(300)]
    segs = N.segment_for_byt5(" ".join(words), target_bytes=120)
    rejoined = " ".join(segs).split()
    assert rejoined == words


def test_segment_prefers_sentence_boundaries() -> None:
    text = "Primum dictum est. Secundum dictum est. Tertium dictum est."
    segs = N.segment_for_byt5(text, target_bytes=25)
    assert all(s.endswith(".") for s in segs), segs


def test_segment_handles_one_oversized_sentence() -> None:
    """A single sentence over budget must fall back to word breaks, not truncate."""
    long_sentence = " ".join(["verbumlongissimum"] * 40) + "."
    segs = N.segment_for_byt5(long_sentence, target_bytes=100)
    assert len(segs) > 1
    assert " ".join(segs).split() == long_sentence.split()


def test_segment_empty() -> None:
    assert N.segment_for_byt5("") == []
    assert N.segment_for_byt5("   ") == []


def test_normalize_long_text_covers_whole_input() -> None:
    """Every segment must reach the model -- the truncation regression."""
    text = " ".join(f"verbum{i}" for i in range(200))
    expected_segments = N.segment_for_byt5(text)
    assert len(expected_segments) > 1

    triple = _fake_model(["OUT"] * len(expected_segments))
    with patch.object(N, "_load_model", return_value=triple):
        out = N.normalize_long_text(text)
    sent = triple[0].call_args[0][0]
    assert len(sent) == len(expected_segments)
    assert out == " ".join(["OUT"] * len(expected_segments))


def test_output_budget_scales_with_input() -> None:
    """A fixed max_new_tokens is what truncated the output; it must scale."""
    short = N._budget(["abc"], None)
    long_ = N._budget(["x" * 400], None)
    assert long_ > short
    assert long_ >= 800  # 400 bytes * 2.0 headroom
    # An explicit value still wins, for reproducing an older run.
    assert N._budget(["x" * 400], 256) == 256


def test_single_line_helper_warns_when_given_long_text() -> None:
    """normalize_medieval_text truncates by design; it must say so."""
    triple = _fake_model(["out"])
    with patch.object(N, "_load_model", return_value=triple):
        with pytest.warns(UserWarning, match="TRUNCATED"):
            N.normalize_medieval_text("x" * (N.MAX_INPUT_BYTES + 50))


# ── hallucination guard ──────────────────────────────────────────────────────


def test_script_drift_detected() -> None:
    """Invented Greek from unreadable Latin input must be caught."""
    assert N.rejects_script_drift(
        "d UMxI5u 1 pos 0. si cilium p. 12e.", "Πολισμοῦς et Πολισμοῦς et Israel"
    )


def test_legitimate_expansion_is_not_flagged() -> None:
    """Real normalization stays in Latin script and must pass."""
    assert not N.rejects_script_drift(
        "uixta numerũ uocabuloꝵ suoꝵ", "juxta numerum vocabulorum suorum"
    )
    assert not N.rejects_script_drift("ñ fecto quic qua", "non fato quidquam")


def test_greek_input_may_keep_greek_output() -> None:
    """The guard is about NEW scripts, not about Greek being forbidden."""
    assert not N.rejects_script_drift("λόγος et uerbum", "λόγος et verbum")


def test_guarded_normalize_falls_back_per_segment() -> None:
    """One bad segment must not discard the good ones around it."""
    text = "primum dictum est. secundum dictum est."
    segs = N.segment_for_byt5(text, target_bytes=25)
    assert len(segs) == 2
    triple = _fake_model(["Πολισμοῦς invented", "secundum dictum est."])
    with patch.object(N, "_load_model", return_value=triple):
        out, rejected = N.normalize_long_text_guarded(text, target_bytes=25)
    assert rejected == 1
    assert "Πολισμ" not in out
    assert segs[0] in out          # bad segment fell back to its input
    assert "secundum dictum est." in out  # good segment kept its normalization


# ── OOM resilience ───────────────────────────────────────────────────────────
#
# Attention memory grows with batch x seqlen^2, so the longest bucket peaks well
# above the average. A run at batch 256 died with CUDA OOM 5,624 chunks into a
# 25,883-chunk corpus. Halving only the failing batch beats choosing a timid
# batch for every bucket.


def test_oom_halves_batch_and_completes() -> None:
    import torch

    triple = _fake_model(["x"])
    tokenizer, model, device = triple
    calls: list[int] = []
    sizes: list[int] = []

    def _tok(texts, **_kw):
        sizes.append(len(texts))
        enc = MagicMock()
        enc.to.return_value = enc
        enc.keys.return_value = ["input_ids"]
        enc.__iter__ = lambda self: iter(["input_ids"])
        enc.__getitem__ = lambda self, k: "TENSOR"
        return enc

    tokenizer.side_effect = _tok

    def _gen(**_kw):
        calls.append(sizes[-1])
        # Fail on the first, full-size batch; succeed once it has been halved.
        if sizes[-1] >= 8:
            raise torch.OutOfMemoryError("simulated")
        return [[0]] * sizes[-1]

    model.generate.side_effect = _gen
    tokenizer.batch_decode.side_effect = lambda *_a, **_k: ["out"] * sizes[-1]

    with patch.object(N, "_load_model", return_value=triple):
        with pytest.warns(UserWarning, match="halving batch"):
            res = N.normalize_lines([f"line{i}" for i in range(8)], batch_size=8)

    assert res == ["out"] * 8
    assert max(calls) >= 8 and min(calls) < 8  # tried big, fell back smaller


def test_oom_on_single_segment_keeps_source() -> None:
    """Unsplittable batch must keep the input, not drop the line."""
    import torch

    triple = _fake_model(["x"])
    tokenizer, model, _d = triple
    tokenizer.side_effect = lambda texts, **_k: MagicMock(
        to=MagicMock(return_value=MagicMock(
            keys=MagicMock(return_value=["input_ids"]),
            __iter__=lambda self: iter(["input_ids"]),
            __getitem__=lambda self, k: "TENSOR",
        ))
    )
    model.generate.side_effect = torch.OutOfMemoryError("always")

    with patch.object(N, "_load_model", return_value=triple):
        with pytest.warns(UserWarning):
            res = N.normalize_lines(["only-line"], batch_size=1)
    assert res == ["only-line"]
