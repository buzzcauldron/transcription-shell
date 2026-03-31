"""User-facing LLM failures (safe to show in GUI / logs; no raw secrets)."""


class LLMProviderError(Exception):
    """Raised when an LLM adapter has a clear, user-facing explanation."""
