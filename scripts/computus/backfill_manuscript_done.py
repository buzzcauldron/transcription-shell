#!/usr/bin/env python3
"""Backfill per-manuscript acquire.DONE markers for jobs already on disk.

Writes jobs/<id>/status/acquire.DONE and harvest done/ index when:
  - images under 00_sources_chunks >= min_images
  - no live acquire_full.pid
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from manuscript_done import (  # noqa: E402
    acquire_running,
    count_images,
    is_done,
    mark_done,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-root", type=Path, required=True)
    ap.add_argument("--harvest-root", type=Path, default=None)
    ap.add_argument("--min-images", type=int, default=5)
    ap.add_argument("--queue", type=Path, action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pe_by: dict[str, int | None] = {}
    host_by: dict[str, str] = {}
    for q in args.queue:
        if not q.is_file():
            continue
        for line in q.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            jid = row.get("job_id")
            if not jid:
                continue
            try:
                pe_by[jid] = int(row["page_estimate"]) if row.get("page_estimate") is not None else None
            except (TypeError, ValueError):
                pe_by[jid] = None
            if row.get("host"):
                host_by[jid] = str(row["host"])

    marked = skipped_run = skipped_few = already = 0
    for job in sorted(args.jobs_root.iterdir()):
        if not job.is_dir():
            continue
        if is_done(job):
            already += 1
            continue
        if acquire_running(job):
            skipped_run += 1
            continue
        nimg = count_images(job / "00_sources_chunks" / "full")
        if nimg < args.min_images:
            # also count under any 00_sources_chunks
            nimg = count_images(job / "00_sources_chunks") if nimg == 0 else nimg
        if nimg < args.min_images:
            skipped_few += 1
            continue
        if args.dry_run:
            print(f"[dry-run] would mark {job.name} n={nimg}")
            marked += 1
            continue
        mark_done(
            job,
            nimg=nimg,
            reason="backfill_disk",
            min_images=args.min_images,
            page_estimate=pe_by.get(job.name),
            host=host_by.get(job.name),
            harvest_root=args.harvest_root,
        )
        marked += 1
    print(
        f"marked={marked} already={already} running_skip={skipped_run} "
        f"few_images={skipped_few}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
