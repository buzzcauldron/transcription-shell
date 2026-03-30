from __future__ import annotations

from transcriber_shell.config import Settings


def test_resolved_model_prefers_default_model():
    s = Settings(
        default_model="custom-model",
        anthropic_model="claude-x",
        openai_model="gpt-x",
        gemini_model="gem-x",
    )
    assert s.resolved_model("anthropic") == "custom-model"
    assert s.resolved_model("openai") == "custom-model"


def test_resolved_model_per_provider_without_override():
    s = Settings(default_model=None, anthropic_model="a", openai_model="b", gemini_model="g")
    assert s.resolved_model("anthropic") == "a"
    assert s.resolved_model("openai") == "b"
