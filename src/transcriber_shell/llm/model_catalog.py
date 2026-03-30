"""Known model IDs per provider for GUI dropdowns.

Grouped into **budget** (free-tier friendly, flash/mini/haiku where vendors offer them) and
**premium** (frontier). Names and availability change; users can always set a custom id.

API billing is always per vendor terms — “free” here means models commonly used on free
quotas or lowest-cost tiers (e.g. Gemini Flash, GPT-4o-mini, Claude Haiku).
"""

from __future__ import annotations

# Anthropic: Haiku = lower cost; Sonnet/Opus = premium (all API usage is paid).
ANTHROPIC_BUDGET_MODELS: tuple[str, ...] = (
    "claude-haiku-4-5-20251001",
    "claude-3-5-haiku-20241022",
    "claude-3-haiku-20240307",
)

ANTHROPIC_PREMIUM_MODELS: tuple[str, ...] = (
    "claude-sonnet-4-20250514",
    "claude-3-5-sonnet-20241022",
    "claude-opus-4-20250514",
    "claude-3-opus-20240229",
)

# OpenAI: mini / nano = budget; 4o / o-series = premium.
OPENAI_BUDGET_MODELS: tuple[str, ...] = (
    "gpt-4o-mini",
    "gpt-4o-mini-2024-07-18",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-0125",
    "o4-mini",
    "o4-mini-2025-04-16",
    "gpt-4.1-nano",
    "gpt-4.1-mini",
)

OPENAI_PREMIUM_MODELS: tuple[str, ...] = (
    "gpt-4o",
    "gpt-4o-2024-08-06",
    "gpt-4o-2024-11-20",
    "gpt-4-turbo",
    "gpt-4-turbo-2024-04-09",
    "chatgpt-4o-latest",
    "o1",
    "o1-2024-12-17",
    "o1-mini",
    "o3-mini",
    "o3-mini-2025-01-31",
    "gpt-4.1",
)

# Google Gemini: Flash/Lite = free-tier & fast; Pro = premium.
GEMINI_BUDGET_MODELS: tuple[str, ...] = (
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
)

GEMINI_PREMIUM_MODELS: tuple[str, ...] = (
    "gemini-2.5-pro",
    "gemini-2.0-pro-exp",
    "gemini-1.5-pro",
    "gemini-1.5-pro-latest",
    "gemini-pro-latest",
)

# Ollama: local, no API key; vision-capable tags (install with `ollama pull <name>`).
OLLAMA_LOCAL_FREE_MODELS: tuple[str, ...] = (
    "llava",
    "llava-phi3",
    "moondream",
    "llama3.2-vision",
    "minicpm-v",
    "qwen2.5vl",
    "bakllava",
    "llava-llama3",
)

OLLAMA_LOCAL_LARGER_MODELS: tuple[str, ...] = (
    "llama3.2-vision:90b",
    "llava:13b",
    "llava:34b",
)


def merged_model_ids_for_selector(
    provider: str,
    *,
    free_only: bool,
    discovered_ollama: list[str] | None = None,
) -> tuple[str, ...]:
    """All distinct model ids for GUI dropdown: budget + premium (sorted), or budget-only if free_only.

    For ollama, appends discovered tags not already in the static lists (same as GUI merge).
    """
    budget_ids, premium_ids = models_for_provider(provider)
    p = (provider or "anthropic").lower().strip()
    if p == "ollama" and discovered_ollama:
        extra = tuple(m for m in discovered_ollama if m not in budget_ids and m not in premium_ids)
        budget_ids = budget_ids + extra
    if free_only:
        pool: tuple[str, ...] = budget_ids
    else:
        seen: list[str] = []
        for m in list(budget_ids) + list(premium_ids):
            if m not in seen:
                seen.append(m)
        pool = tuple(seen)
    return tuple(sorted(pool))


def models_for_provider(provider: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (budget_models, premium_models) for provider name."""
    p = (provider or "anthropic").lower().strip()
    if p == "openai":
        return (OPENAI_BUDGET_MODELS, OPENAI_PREMIUM_MODELS)
    if p == "gemini":
        return (GEMINI_BUDGET_MODELS, GEMINI_PREMIUM_MODELS)
    if p == "ollama":
        return (OLLAMA_LOCAL_FREE_MODELS, OLLAMA_LOCAL_LARGER_MODELS)
    return (ANTHROPIC_BUDGET_MODELS, ANTHROPIC_PREMIUM_MODELS)


def default_model_for_provider(provider: str, settings: object | None = None) -> str:
    """Settings default model id for provider (from config)."""
    if settings is None:
        from transcriber_shell.config import Settings

        settings = Settings()
    return settings.resolved_model(provider)
