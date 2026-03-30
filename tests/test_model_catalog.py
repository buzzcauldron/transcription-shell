from __future__ import annotations

from transcriber_shell.llm.model_catalog import (
    ANTHROPIC_BUDGET_MODELS,
    GEMINI_PREMIUM_MODELS,
    merged_model_ids_for_selector,
    models_for_provider,
)


def test_models_for_provider_shapes() -> None:
    b, p = models_for_provider("anthropic")
    assert len(b) >= 2 and len(p) >= 2
    assert set(b) & set(p) == set()

    b2, p2 = models_for_provider("openai")
    assert "gpt-4o-mini" in b2
    assert "gpt-4o" in p2 or "gpt-4o-2024-08-06" in p2

    b3, p3 = models_for_provider("gemini")
    assert any("flash" in m for m in b3)
    assert GEMINI_PREMIUM_MODELS[0] in p3


def test_anthropic_haiku_in_budget() -> None:
    assert "claude-3-5-haiku-20241022" in ANTHROPIC_BUDGET_MODELS


def test_ollama_catalog() -> None:
    b, p = models_for_provider("ollama")
    assert "llava" in b
    assert len(p) >= 1


def test_merged_model_ids_for_selector_union() -> None:
    full = merged_model_ids_for_selector("openai", free_only=False, discovered_ollama=None)
    assert "gpt-4o-mini" in full and "gpt-4o" in full
    budget_only = merged_model_ids_for_selector("openai", free_only=True, discovered_ollama=None)
    assert "gpt-4o-mini" in budget_only
    assert "gpt-4o" not in budget_only


def test_merged_model_ids_ollama_appends_discovered() -> None:
    m = merged_model_ids_for_selector(
        "ollama",
        free_only=False,
        discovered_ollama=["custom-tag"],
    )
    assert "custom-tag" in m

