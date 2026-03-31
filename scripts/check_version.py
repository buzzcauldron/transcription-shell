#!/usr/bin/env python3
"""Exit non-zero if VERSION and pyproject.toml [project].version differ."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    version_file = root / "VERSION"
    pyproject = root / "pyproject.toml"
    vf = version_file.read_text(encoding="utf-8").strip()
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    pv = (data.get("project") or {}).get("version", "")
    if vf != pv:
        print(
            f"VERSION mismatch: VERSION={vf!r} pyproject.toml [project].version={pv!r}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
