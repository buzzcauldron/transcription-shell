#!/usr/bin/env python3
"""Manual smoke: run Glyph Machina line download only (requires playwright + network).

Usage:
  python scripts/gm_smoke_test.py /path/to/cropped.jpg [job_id]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running without installing the package
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from transcriber_shell.glyph_machina.workflow import GlyphMachinaError, fetch_lines_xml


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/gm_smoke_test.py <cropped.jpg> [job_id]", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    job_id = sys.argv[2] if len(sys.argv) > 2 else "smoke"
    try:
        out = fetch_lines_xml(path, job_id)
        print(out)
        return 0
    except GlyphMachinaError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
