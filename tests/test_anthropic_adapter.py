from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

import anthropic
from transcriber_shell.config import Settings
from transcriber_shell.llm.adapters import anthropic as anthropic_adapter
from transcriber_shell.llm.errors import LLMProviderError
from transcriber_shell.llm.transcribe import TranscribeResult

_PATCH_ANTHROPIC_CLIENT = "transcriber_shell.llm.adapters.anthropic.anthropic.Anthropic"


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _resp(status: int) -> httpx.Response:
    return httpx.Response(status, request=_req())


def test_transcribe_success(tmp_path: Path) -> None:
    img = tmp_path / "p.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    stream_obj = MagicMock()
    stream_obj.get_final_text.return_value = "yaml: ok"
    _u = MagicMock()
    _u.input_tokens = 1
    _u.output_tokens = 1
    _fm = MagicMock()
    _fm.usage = _u
    stream_obj.get_final_message.return_value = _fm
    cm = MagicMock()
    cm.__enter__.return_value = stream_obj
    cm.__exit__.return_value = None
    with patch(_PATCH_ANTHROPIC_CLIENT) as MockCl:
        client_inst = MockCl.return_value
        client_inst.messages.stream.return_value = cm
        out = anthropic_adapter.transcribe_anthropic(
            image_path=img,
            system="sys",
            user_text="user",
            settings=Settings(anthropic_api_key="sk-test", anthropic_max_retries=0),
        )
    assert isinstance(out, TranscribeResult)
    assert out.text == "yaml: ok"
    assert out.usage == {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
    client_inst.messages.stream.assert_called_once()


def test_authentication_maps_to_llm_provider_error(tmp_path: Path) -> None:
    img = tmp_path / "p.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    cm = MagicMock()
    cm.__enter__.side_effect = anthropic.AuthenticationError(
        "invalid", response=_resp(401), body=None
    )
    with patch(_PATCH_ANTHROPIC_CLIENT) as MockCl:
        MockCl.return_value.messages.stream.return_value = cm
        with pytest.raises(LLMProviderError) as ei:
            anthropic_adapter.transcribe_anthropic(
                image_path=img,
                system="s",
                user_text="u",
                settings=Settings(anthropic_api_key="sk-bad", anthropic_max_retries=0),
            )
    assert "API key" in str(ei.value) or "key" in str(ei.value).lower()


def test_rate_limit_retries_then_succeeds(tmp_path: Path) -> None:
    img = tmp_path / "p.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    stream_ok = MagicMock()
    stream_ok.get_final_text.return_value = "ok"
    _u = MagicMock()
    _u.input_tokens = 1
    _u.output_tokens = 1
    _fm = MagicMock()
    _fm.usage = _u
    stream_ok.get_final_message.return_value = _fm
    cm_ok = MagicMock()
    cm_ok.__enter__.return_value = stream_ok
    cm_ok.__exit__.return_value = None
    cm_rl = MagicMock()
    cm_rl.__enter__.side_effect = anthropic.RateLimitError(
        "rl", response=_resp(429), body=None
    )
    streams = [cm_rl, cm_ok]

    def stream_side_effect(*_a: object, **_k: object) -> MagicMock:
        return streams.pop(0)

    with patch(_PATCH_ANTHROPIC_CLIENT) as MockCl:
        MockCl.return_value.messages.stream.side_effect = stream_side_effect
        with patch.object(anthropic_adapter.time, "sleep", autospec=True):
            out = anthropic_adapter.transcribe_anthropic(
                image_path=img,
                system="s",
                user_text="u",
                settings=Settings(
                    anthropic_api_key="sk-test",
                    anthropic_max_retries=2,
                ),
            )
    assert isinstance(out, TranscribeResult)
    assert out.text == "ok"
    assert MockCl.return_value.messages.stream.call_count == 2


def test_bad_request_model_hint(tmp_path: Path) -> None:
    img = tmp_path / "p.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    cm = MagicMock()
    cm.__enter__.side_effect = anthropic.BadRequestError(
        "unknown model: x", response=_resp(400), body=None
    )
    with patch(_PATCH_ANTHROPIC_CLIENT) as MockCl:
        MockCl.return_value.messages.stream.return_value = cm
        with pytest.raises(LLMProviderError) as ei:
            anthropic_adapter.transcribe_anthropic(
                image_path=img,
                system="s",
                user_text="u",
                settings=Settings(anthropic_api_key="sk-test", anthropic_max_retries=0),
            )
    assert "model" in str(ei.value).lower()


def test_timeout_message(tmp_path: Path) -> None:
    img = tmp_path / "p.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    cm = MagicMock()
    cm.__enter__.side_effect = anthropic.APITimeoutError(_req())
    with patch(_PATCH_ANTHROPIC_CLIENT) as MockCl:
        MockCl.return_value.messages.stream.return_value = cm
        with pytest.raises(LLMProviderError) as ei:
            anthropic_adapter.transcribe_anthropic(
                image_path=img,
                system="s",
                user_text="u",
                settings=Settings(anthropic_api_key="sk-test", anthropic_max_retries=0),
            )
    assert "timed out" in str(ei.value).lower() or "timeout" in str(ei.value).lower()
