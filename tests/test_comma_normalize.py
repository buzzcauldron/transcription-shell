"""CoMMA ByT5 normalization helper (mocked — no HF download in CI)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from transcriber_shell.comma.normalize import normalize_medieval_text


def test_normalize_medieval_text_mock() -> None:
    mock_pipe = MagicMock(return_value=[{"generated_text": "scribo uobis, non Pauli uel Donati"}])
    with patch("transcriber_shell.comma.normalize._load_pipeline", return_value=mock_pipe):
        out = normalize_medieval_text("Scͥbo uobiᷤᷤ ñ pauli ł donati.")
    assert "scribo" in out
    mock_pipe.assert_called_once()
    call_arg = mock_pipe.call_args[0][0]
    assert "Sc" in call_arg  # NFD-normalized input


def test_normalize_empty_returns_empty() -> None:
    assert normalize_medieval_text("") == ""
    assert normalize_medieval_text("   ") == ""
