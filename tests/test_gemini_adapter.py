from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

from transcriber_shell.config import Settings
from transcriber_shell.llm.adapters import gemini as gemini_adapter


def _stub_provider_adapters() -> None:
    mod = types.ModuleType("provider_adapters")
    mod.augment_system_for_provider = lambda sys_txt, _p: sys_txt
    sys.modules["provider_adapters"] = mod


def _fake_client_factory(calls: list[str], fail_first: str, ok_text: str = "ok"):
    class FakeResp:
        text = ok_text
        usage_metadata = None

    class FakeModels:
        def generate_content(self, **kw):
            mid = kw["model"]
            calls.append(mid)
            if mid == fail_first:
                err = RuntimeError("429 RESOURCE_EXHAUSTED free_tier")
                err.status_code = 429  # type: ignore[attr-defined]
                raise err
            return FakeResp()

    class FakeClient:
        def __init__(self, **_k):
            self.models = FakeModels()

    return FakeClient


def test_gemini_cycles_model_on_429(monkeypatch) -> None:
    gemini_adapter._reset_gemini_cycle_for_tests()
    monkeypatch.setenv("GEMINI_MODEL_CYCLE", "gemini-2.5-flash,gemini-2.0-flash")
    calls: list[str] = []
    FakeClient = _fake_client_factory(calls, "gemini-2.5-flash")
    _stub_provider_adapters()
    with (
        patch("google.genai.Client", FakeClient),
        patch("google.genai.types", MagicMock()),
        patch(
            "transcriber_shell.protocol_paths.ensure_prompt_builder_on_path",
            lambda *_a, **_k: None,
        ),
    ):
        out = gemini_adapter.transcribe_gemini(
            image_path=None,
            system="s",
            user_text="u",
            model="gemini-2.5-flash",
            settings=Settings(google_api_key="x", gemini_model="gemini-2.5-flash"),
        )
    assert out.text == "ok"
    assert calls[0] == "gemini-2.5-flash"
    assert "gemini-2.0-flash" in calls


def test_gemini_correct_mode_does_not_cycle_on_429(monkeypatch) -> None:
    gemini_adapter._reset_gemini_cycle_for_tests()
    monkeypatch.setenv("GEMINI_MODEL_CYCLE", "gemini-2.5-flash,gemini-2.0-flash")
    calls: list[str] = []
    FakeClient = _fake_client_factory(calls, "gemini-2.5-flash")
    _stub_provider_adapters()
    with (
        patch("google.genai.Client", FakeClient),
        patch("google.genai.types", MagicMock()),
        patch(
            "transcriber_shell.protocol_paths.ensure_prompt_builder_on_path",
            lambda *_a, **_k: None,
        ),
    ):
        try:
            gemini_adapter.transcribe_gemini(
                image_path=None,
                system="s",
                user_text="u",
                model="gemini-2.5-flash",
                settings=Settings(
                    google_api_key="x",
                    gemini_model="gemini-2.5-flash",
                    llm_mode="correct",
                ),
            )
        except RuntimeError as exc:
            assert "429" in str(exc)
        else:
            raise AssertionError("correct mode should raise on 429 instead of cycling")
    assert calls == ["gemini-2.5-flash"]


def test_gemini_remembers_exhausted_model(monkeypatch) -> None:
    gemini_adapter._reset_gemini_cycle_for_tests()
    monkeypatch.setenv("GEMINI_MODEL_CYCLE", "gemini-2.5-flash,gemini-2.0-flash")
    calls: list[str] = []
    FakeClient = _fake_client_factory(calls, "gemini-2.5-flash")
    settings = Settings(google_api_key="x", gemini_model="gemini-2.5-flash")
    _stub_provider_adapters()
    with (
        patch("google.genai.Client", FakeClient),
        patch("google.genai.types", MagicMock()),
        patch(
            "transcriber_shell.protocol_paths.ensure_prompt_builder_on_path",
            lambda *_a, **_k: None,
        ),
    ):
        gemini_adapter.transcribe_gemini(
            image_path=None, system="s", user_text="u", model="gemini-2.5-flash", settings=settings
        )
        gemini_adapter.transcribe_gemini(
            image_path=None, system="s", user_text="u", model="gemini-2.5-flash", settings=settings
        )
    assert calls.count("gemini-2.5-flash") == 1
    assert calls.count("gemini-2.0-flash") == 2
