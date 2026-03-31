#!/usr/bin/env python3
"""Verify Anthropic API credentials with a minimal Messages request.

Reads ``ANTHROPIC_API_KEY`` / ``TRANSCRIBER_SHELL_ANTHROPIC_API_KEY`` via Settings (``.env`` supported).
Exits 0 on success, 1 on missing key or authentication failure, 2 on other API errors.

Uses a tiny ``max_tokens=1`` completion (may incur minimal usage).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import anthropic  # noqa: E402

from transcriber_shell.config import Settings  # noqa: E402

# Cheapest widely available model for a ping; override only if default model is unavailable.
_PING_MODEL = "claude-3-haiku-20240307"


def main() -> int:
    s = Settings()
    key = (s.anthropic_api_key or "").strip()
    if not key:
        print(
            "No Anthropic API key found. Set ANTHROPIC_API_KEY or "
            "TRANSCRIBER_SHELL_ANTHROPIC_API_KEY in .env or the environment.",
            file=sys.stderr,
        )
        return 1

    client = anthropic.Anthropic(api_key=key)
    try:
        client.messages.create(
            model=_PING_MODEL,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except anthropic.AuthenticationError as e:
        print(f"Anthropic authentication failed: {e}", file=sys.stderr)
        print(
            "Check ANTHROPIC_API_KEY (no extra spaces, key not revoked). "
            "See docs/claude_anthropic_reference.md.",
            file=sys.stderr,
        )
        return 1
    except anthropic.APIError as e:
        print(f"Anthropic API error (not necessarily bad key): {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 2

    print("Anthropic API key accepted (minimal request succeeded).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
