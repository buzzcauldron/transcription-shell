#!/usr/bin/env python3
"""Build a reviewed HTR downstream queue from harvest jobs with disk images.

Only enqueue jobs that:
  - have enough images
  - are not robots-blocked
  - by default have per-manuscript status/acquire.DONE (acquire finished)

Does not start HTR; emits JSONL for the supervisor.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from manuscript_done import DONE_NAME, acquire_running, is_done  # noqa: E402

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2", ".webp"}


def count_images(job: Path) -> int:
    img_root = job / "00_sources_chunks"
    if not img_root.is_dir():
        return 0
    n = 0
    for p in img_root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            n += 1
    return n


def count_yaml(job: Path) -> int:
    art = job / "03_artifacts_2500"
    if not art.is_dir():
        return 0
    return sum(1 for _ in art.rglob("*_transcription.yaml"))


def load_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def role_map(registry: Path | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for rec in load_jsonl(registry):
        rid = rec.get("id")
        slug = rec.get("cohort_slug")
        role = rec.get("material_role") or "direct_computus"
        if rid:
            out[str(rid)] = role
        if slug:
            out[str(slug)] = role
        # job_id style
        if rid:
            s = re.sub(r"[^a-z0-9]+", "_", str(rid).lower())
            s = re.sub(r"_+", "_", s).strip("_")[:60]
            out[s] = role
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-root", type=Path, required=True)
    ap.add_argument("--acquire-queue", type=Path, default=None)
    ap.add_argument("--registry", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-images", type=int, default=10)
    ap.add_argument(
        "--include-prefix",
        nargs="*",
        default=None,
        help="Only job_id prefixes (e.g. clat_ bnf_ bsb_). Default: all ready jobs.",
    )
    ap.add_argument(
        "--exclude-counterpoints",
        action="store_true",
        help="Omit material_role=counterpoint from the HTR queue",
    )
    ap.add_argument(
        "--require-acquire-done",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Only enqueue jobs with status/acquire.DONE (default: true)",
    )
    ap.add_argument(
        "--allow-in-progress",
        action="store_true",
        help="Also enqueue jobs with enough images even if acquire still running",
    )
    args = ap.parse_args()

    roles = role_map(args.registry)
    queue_rows = load_jsonl(args.acquire_queue)
    by_jid = {r["job_id"]: r for r in queue_rows if r.get("job_id")}

    candidates: set[str] = set(by_jid)
    if args.jobs_root.is_dir():
        for d in args.jobs_root.iterdir():
            if d.is_dir() and (d / "00_sources_chunks").is_dir():
                candidates.add(d.name)

    out_rows: list[dict[str, Any]] = []
    for jid in sorted(candidates):
        if args.include_prefix:
            if not any(jid.startswith(p) for p in args.include_prefix):
                continue
        job = args.jobs_root / jid
        if not job.is_dir():
            continue
        # Offloaded to Bridges (MS HTR or print OCR) — skip local Gemini watchers
        if (job / "status" / "htr_bridges.CLAIMED").is_file():
            continue
        if (job / "status" / "print_ocr_bridges.CLAIMED").is_file():
            continue
        nimg = count_images(job)
        if nimg < args.min_images:
            continue
        q = by_jid.get(jid) or {}
        if q.get("robots_allowed") is False:
            continue
        done_ms = is_done(job)
        running = acquire_running(job)
        if running and not args.allow_in_progress:
            continue
        if args.require_acquire_done and not done_ms and not args.allow_in_progress:
            # Idle jobs with enough images are eligible; markers optional until backfill
            # but still in-flight scrapes are excluded above.
            if running:
                continue
        role = roles.get(jid) or q.get("material_role") or "direct_computus"
        if args.exclude_counterpoints and role == "counterpoint":
            continue
        ny = count_yaml(job)
        doneish = ny > 0 and nimg > 0 and ny * 10 >= nimg * 9
        reason = "acquire_done" if done_ms else "images_ready_idle"
        out_rows.append(
            {
                "job_id": jid,
                "job_dir": str(job),
                "images": nimg,
                "yaml_pages": ny,
                "transcription_doneish": doneish,
                "acquire_done": done_ms,
                "url": q.get("url"),
                "host": q.get("host"),
                "material_role": role,
                "record_id": q.get("record_id"),
                "scraper": q.get("scraper", "strigil"),
                "reason": reason,
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    pending = sum(1 for r in out_rows if not r["transcription_doneish"])
    print(
        f"Wrote {len(out_rows)} HTR queue rows "
        f"({pending} pending, {len(out_rows) - pending} doneish) → {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
