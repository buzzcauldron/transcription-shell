#!/usr/bin/env python3
"""Validate human GT PAGE XML vs image (wrapper for CI / PATH)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from transcriber_shell.xml_tools.validate_gt_pagexml import cli_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cli_main())
