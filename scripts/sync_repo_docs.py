#!/usr/bin/env python3
"""Keep ``VERSION`` and marked **markdown** sections aligned with ``pyproject.toml``.

Canonical metadata lives in ``pyproject.toml`` ``[project]``. After **pulling** or changing the
version / ``requires-python``, run::

    python scripts/sync_repo_docs.py

Use ``--check`` in CI to fail if files are out of date.

Markdown files contain blocks::

    <!-- transcriber-shell-sync:pyproject.version -->
    ... generated one-liner ...
    <!-- transcriber-shell-sync:end:pyproject.version -->
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

from pyproject_meta import (  # noqa: E402
    read_pyproject_version,
    read_requires_python,
    requires_python_display,
    sync_version_file,
)

BLOCK_ID = "pyproject.version"


def _render_version_blurb(link_href: str, pyproject: Path) -> str:
    v = read_pyproject_version(pyproject)
    rp_disp = requires_python_display(read_requires_python(pyproject))
    return (
        f"**Version {v}** · Python {rp_disp} — canonical metadata in "
        f"[`pyproject.toml`]({link_href}). After a pull or version bump, run "
        f"`python scripts/sync_repo_docs.py`."
    )


def _replace_block(text: str, block_id: str, new_inner: str) -> tuple[str, bool]:
    begin = f"<!-- transcriber-shell-sync:{block_id} -->"
    end = f"<!-- transcriber-shell-sync:end:{block_id} -->"
    pattern = re.compile(
        re.escape(begin) + r"\s*[\s\S]*?\s*" + re.escape(end),
        re.MULTILINE,
    )
    if not pattern.search(text):
        return text, False
    inner = new_inner.strip()
    replacement = f"{begin}\n{inner}\n{end}"
    return pattern.sub(replacement, text, count=1), True


def _markdown_specs(root: Path) -> list[tuple[Path, str]]:
    return [
        (root / "README.md", "pyproject.toml"),
        (root / "PACKAGING.md", "pyproject.toml"),
        (root / "docs" / "claude.md", "../pyproject.toml"),
    ]


def _sync_markdown(root: Path, *, write: bool) -> int:
    pyproject = root / "pyproject.toml"
    for path, link in _markdown_specs(root):
        if not path.is_file():
            print(f"warning: missing file, skip: {path}", file=sys.stderr)
            continue
        text = path.read_text(encoding="utf-8")
        blurb = _render_version_blurb(link, pyproject)
        new_text, found = _replace_block(text, BLOCK_ID, blurb)
        if not found:
            print(
                f"error: sync markers not found in {path} "
                f"(expected <!-- transcriber-shell-sync:{BLOCK_ID} --> … end:{BLOCK_ID} -->)",
                file=sys.stderr,
            )
            return 1
        if new_text != text:
            if write:
                path.write_text(new_text, encoding="utf-8")
                print(f"updated {path.relative_to(root)}")
            else:
                print(
                    f"out of date: {path.relative_to(root)} (run python scripts/sync_repo_docs.py)",
                    file=sys.stderr,
                )
                return 1
    return 0


def _version_file_matches(root: Path) -> bool:
    vf = root / "VERSION"
    intended = read_pyproject_version(root / "pyproject.toml")
    if not intended:
        return False
    if not vf.is_file():
        return False
    return vf.read_text(encoding="utf-8").strip() == intended


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if VERSION or markdown blocks differ from pyproject.toml (no writes)",
    )
    args = ap.parse_args()
    root = _ROOT

    if args.check:
        if not _version_file_matches(root):
            print(
                "VERSION does not match pyproject.toml [project].version.\n"
                "Run: python scripts/sync_repo_docs.py",
                file=sys.stderr,
            )
            return 1
        return _sync_markdown(root, write=False)

    if sync_version_file(root) != 0:
        return 1
    return _sync_markdown(root, write=True)


if __name__ == "__main__":
    raise SystemExit(main())
