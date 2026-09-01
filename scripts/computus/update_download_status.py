#!/usr/bin/env python3
"""Sync acquisition.downloaded_* fields from on-disk job trees into a registry JSONL.

For each registry record, derive job_id the same way as build_acquire_queue and count
image files under jobs/<id>/00_sources_chunks/full. Updates status to downloaded when
enough images are present.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

IMG_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2", ".webp"}


def job_id(rec: dict[str, Any]) -> str:
    if rec.get("cohort_slug"):
        return str(rec["cohort_slug"])[:60]
    base = rec.get("id") or "ms"
    s = re.sub(r"[^a-z0-9]+", "_", str(base).lower())
    return re.sub(r"_+", "_", s).strip("_")[:60]


def count_images(path: Path) -> int:
    if not path.is_dir():
        return 0
    n = 0
    for p in path.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMG_SUFFIXES:
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", type=Path, required=True)
    ap.add_argument("--jobs-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-images", type=int, default=5)
    args = ap.parse_args()

    updated = 0
    downloaded = 0
    rows: list[dict[str, Any]] = []
    with args.registry.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            jid = job_id(rec)
            job = args.jobs_root / jid
            img_dir = job / "00_sources_chunks" / "full"
            n = count_images(img_dir)
            acq = rec.setdefault("acquisition", {})
            if n > 0:
                acq["downloaded_pages"] = n
                acq["job_dir"] = str(job)
                if n >= args.min_images and acq.get("status") in (
                    "confirmed",
                    "needs_review",
                    "has_url",
                    "url_failed",
                    "downloaded",
                    "pending",
                ):
                    if acq.get("status") != "local":
                        acq["status"] = "downloaded"
                    downloaded += 1
                updated += 1
            rows.append(rec)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(
        f"Wrote {args.out} rows={len(rows)} with_images={updated} "
        f"status_downloaded={downloaded}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
