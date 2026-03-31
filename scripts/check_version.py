#!/usr/bin/env python3
"""Exit non-zero if VERSION and pyproject.toml [project].version differ.

Single source of truth: ``pyproject.toml`` ``[project].version``. After bumping the version there
(or after pulling a change that updated it), run::

    python scripts/sync_repo_docs.py

That updates ``VERSION`` and marked sections in ``README.md``, ``PACKAGING.md``, and ``docs/claude.md``.
You can still run ``python scripts/check_version.py --sync`` to update **only** ``VERSION``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from pyproject_meta import read_pyproject_version, sync_version_file  # noqa: E402


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    if "--sync" in sys.argv:
        return sync_version_file(root)

    version_file = root / "VERSION"
    pyproject = root / "pyproject.toml"
    vf = version_file.read_text(encoding="utf-8").strip()
    pv = read_pyproject_version(pyproject)
    if vf != pv:
        print(
            f"VERSION mismatch: VERSION={vf!r} pyproject.toml [project].version={pv!r}\n"
            "Fix: run:\n"
            "  python scripts/sync_repo_docs.py\n"
            "or (VERSION file only):\n"
            "  python scripts/check_version.py --sync",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
