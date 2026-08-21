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
    """An empty generation must not silently delete the line."""
    triple = _fake_model(["", "ok"])
    with patch.object(N, "_load_model", return_value=triple):
        out = N.normalize_lines(["keepme", "other"])
    assert out == ["keepme", "ok"]
