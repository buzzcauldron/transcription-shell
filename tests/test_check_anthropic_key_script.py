"""Smoke tests for scripts/check_anthropic_key.py."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "check_anthropic_key.py"


def test_check_anthropic_key_exits_nonzero_without_key(tmp_path) -> None:
    """No .env in cwd and no key env vars -> exit 1."""
    env = os.environ.copy()
    for k in (
        "ANTHROPIC_API_KEY",
        "TRANSCRIBER_SHELL_ANTHROPIC_API_KEY",
    ):
        env.pop(k, None)
    r = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1
    assert "No Anthropic API key" in (r.stderr or "")
