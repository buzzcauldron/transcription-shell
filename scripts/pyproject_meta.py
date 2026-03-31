"""Read `[project]` from ``pyproject.toml`` (repo root). Used by version checks and doc sync."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any


def load_project_table(pyproject: Path) -> dict[str, Any]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    proj = data.get("project")
    return proj if isinstance(proj, dict) else {}


def read_pyproject_version(pyproject: Path) -> str:
    pv = load_project_table(pyproject).get("version", "")
    if not isinstance(pv, str) or not pv.strip():
        return ""
    return pv.strip()


def read_requires_python(pyproject: Path) -> str:
    rp = load_project_table(pyproject).get("requires-python", "")
    if not isinstance(rp, str):
        return ""
    return rp.strip()


def requires_python_display(requires_python: str) -> str:
    """e.g. ``>=3.11`` → ``3.11+`` for README-style blurbs."""
    rp = requires_python.strip()
    if rp.startswith(">="):
        return rp[2:].strip() + "+"
    return rp or "see pyproject.toml"


def sync_version_file(root: Path) -> int:
    """Write ``VERSION`` from ``[project].version``."""
    version_file = root / "VERSION"
    pyproject = root / "pyproject.toml"
    pv = read_pyproject_version(pyproject)
    if not pv:
        print(
            "error: pyproject.toml missing non-empty [project].version",
            file=sys.stderr,
        )
        return 1
    version_file.write_text(pv + "\n", encoding="utf-8")
    print(f"Wrote VERSION = {pv!r} (from pyproject.toml)")
    return 0
