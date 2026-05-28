#!/usr/bin/env python3
"""Emit TSV acquire plan rows: id, url_or_path, strigil_flags, kind."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def strigil_flags(url: str) -> str:
    if any(x in url for x in ("bl.uk", "wellcomecollection", "morgan.org")):
        return "--js"
    if "gallica.bnf.fr" in url:
        return "--source iiif"
    return ""


def main() -> None:
    manifest_path = Path(sys.argv[1])
    want = set(sys.argv[2:]) if len(sys.argv) > 2 else None
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    for ms in data.get("manuscripts", []):
        mid = ms["id"]
        if want and mid not in want:
            continue
        if ms.get("local_image_root"):
            print(f"{mid}|{ms['local_image_root']}||local")
            continue
        if not ms.get("strigil_acquire") or not ms.get("archive_ms_page"):
            continue
        url = ms["archive_ms_page"]
        print(f"{mid}|{url}|{strigil_flags(url)}|remote")


if __name__ == "__main__":
    main()
