"""Smoke tests for scripts/check_version.py (VERSION vs pyproject)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_check_version_script_matches_repo() -> None:
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_version.py")],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr


def test_sync_repo_docs_check_passes_on_repo() -> None:
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, str(root / "scripts" / "sync_repo_docs.py"), "--check"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr


def test_check_version_sync_is_idempotent(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    vf = root / "VERSION"
    before = vf.read_text(encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_version.py"), "--sync"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    after = vf.read_text(encoding="utf-8")
    assert after == before
