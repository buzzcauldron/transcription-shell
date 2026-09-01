#!/usr/bin/env python3
"""Sample-validate acquired jobs for each host/repository represented in the harvest.

Picks up to N jobs per host that already have images, checks:
  - image count vs page_estimate (when known)
  - presence of source_url / acquire_meta
  - basic filename folio-order monotonicity when numeric stems appear
Writes reports/repository_samples.json + section for the markdown audit.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IMG_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2", ".webp"}


def host_of(url: str | None) -> str:
    if not url:
        return ""
    return urllib.parse.urlparse(url).netloc.lower()


def list_images(img_dir: Path) -> list[Path]:
    if not img_dir.is_dir():
        return []
    return sorted(
        p
        for p in img_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in IMG_SUFFIXES
    )


def order_score(paths: list[Path]) -> dict[str, Any]:
    nums: list[int] = []
    for p in paths:
        m = re.search(r"(\d{2,})(?=\.[^.]+$)", p.name)
        if m:
            nums.append(int(m.group(1)))
    if len(nums) < 4:
        return {"checked": False, "reason": "insufficient_numeric_stems"}
    # Monotonic non-decreasing after sort of names is expected if listing is sorted
    diffs = [b - a for a, b in zip(nums, nums[1:])]
    neg = sum(1 for d in diffs if d < 0)
    return {
        "checked": True,
        "n_numeric": len(nums),
        "disorder_pairs": neg,
        "ok": neg <= max(2, len(diffs) // 20),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-root", type=Path, required=True)
    ap.add_argument("--queue", type=Path, action="append", default=[])
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--per-host", type=int, default=2)
    ap.add_argument("--min-images", type=int, default=5)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    by_host: dict[str, list[dict[str, Any]]] = defaultdict(list)
    queues = list(args.queue)
    if not queues:
        # fall back: scan job dirs with source_url.txt
        for job in sorted(args.jobs_root.iterdir()):
            if not job.is_dir():
                continue
            suf = job / "source_url.txt"
            if not suf.exists():
                continue
            url = suf.read_text(encoding="utf-8", errors="replace").strip()
            h = host_of(url) or "unknown"
            by_host[h].append({"job_id": job.name, "url": url, "shelfmark": ""})
    else:
        for qpath in queues:
            if not qpath.is_file():
                continue
            with qpath.open(encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    h = row.get("host") or host_of(row.get("url")) or "unknown"
                    by_host[h].append(row)

    samples: list[dict[str, Any]] = []
    hosts_ok = 0
    hosts_fail = 0
    hosts_skip = 0
    for host, rows in sorted(by_host.items(), key=lambda x: -len(x[1])):
        taken = 0
        for row in rows:
            if taken >= args.per_host:
                break
            jid = row.get("job_id") or row.get("id")
            if not jid:
                continue
            job = args.jobs_root / str(jid)
            images = list_images(job / "00_sources_chunks" / "full")
            if len(images) < args.min_images:
                continue
            meta_path = job / "acquire_meta.json"
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    meta = {}
            pe = row.get("page_estimate") or meta.get("page_estimate")
            try:
                pe_int = int(pe) if pe is not None else None
            except (TypeError, ValueError):
                pe_int = None
            order = order_score(images)
            page_agree = None
            if pe_int and pe_int > 0:
                ratio = len(images) / pe_int
                page_agree = 0.5 <= ratio <= 1.2 or abs(len(images) - pe_int) <= 5
            ok = bool(images) and (order.get("ok", True)) and (
                page_agree is not False
            )
            samples.append(
                {
                    "host": host,
                    "job_id": jid,
                    "url": row.get("url") or meta.get("url"),
                    "shelfmark": row.get("shelfmark") or "",
                    "n_images": len(images),
                    "page_estimate": pe_int,
                    "page_count_agrees": page_agree,
                    "order": order,
                    "has_meta": bool(meta),
                    "ok": ok,
                }
            )
            taken += 1
            if ok:
                hosts_ok += 1
            else:
                hosts_fail += 1
        if taken == 0:
            hosts_skip += 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_hosts_in_queues": len(by_host),
        "n_samples": len(samples),
        "samples_ok": hosts_ok,
        "samples_fail": hosts_fail,
        "hosts_without_download": hosts_skip,
        "samples": samples,
    }
    out = args.out_dir / "repository_samples.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    md = [
        "# Repository sample validation",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- Hosts seen in queues: **{report['n_hosts_in_queues']}**",
        f"- Samples checked: **{report['n_samples']}** (ok={hosts_ok}, fail={hosts_fail})",
        f"- Hosts with no eligible download yet: **{hosts_skip}**",
        "",
        "| Host | Job | Images | Est | Agree | Order | OK |",
        "|---|---|---:|---:|:---:|:---:|:---:|",
    ]
    for s in samples:
        md.append(
            f"| {s['host']} | `{s['job_id']}` | {s['n_images']} | "
            f"{s['page_estimate'] or '—'} | {s['page_count_agrees']} | "
            f"{s['order'].get('ok', '—')} | {s['ok']} |"
        )
    (args.out_dir / "REPOSITORY_SAMPLES.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Wrote {out} samples={len(samples)} ok={hosts_ok} fail={hosts_fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
