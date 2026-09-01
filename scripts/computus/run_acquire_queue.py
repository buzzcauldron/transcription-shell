#!/usr/bin/env python3
"""Run strigil image acquisition from a structured JSONL queue.

Safe for remote hosts: per-host concurrency caps, exponential backoff,
robots-aware skip, resume if images already present.

Writes per-manuscript DONE markers (status/acquire.DONE + harvest done/)
so post-harvest HTR can start before the full queue finishes.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from manuscript_done import (  # noqa: E402
    count_images,
    finalize_after_acquire,
    mark_done,
)
from strigil_flags import strigil_cmd, strigil_flags, with_parallel_workers  # noqa: E402


HOST_CONCURRENCY = {
    "gallica.bnf.fr": 1,
    "archive.org": 3,
    "iiif.archive.org": 3,
    "iiif.lib.harvard.edu": 0,  # often robots-blocked
    "digi.vatlib.it": 2,
    "api.digitale-sammlungen.de": 2,
    "www.e-codices.unifr.ch": 2,
    "e-codices.unifr.ch": 2,
    "iiif.bodleian.ox.ac.uk": 2,
}
DEFAULT_HOST_CONCURRENCY = 2


def load_queue(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def active_for_host(running: dict[str, subprocess.Popen], host: str) -> int:
    return sum(1 for key in running if key.split("|", 1)[0] == host)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--queue", type=Path, required=True)
    ap.add_argument("--jobs-root", type=Path, required=True)
    ap.add_argument("--strigil-dir", type=Path, required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--global-concurrency", type=int, default=6)
    ap.add_argument(
        "--strigil-workers",
        type=int,
        default=8,
        help="Parallel image downloads per manuscript (Gallica stays sequential).",
    )
    ap.add_argument("--min-images-done", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--harvest-root",
        type=Path,
        default=None,
        help="Write harvest/done/<job_id> index for post-harvest waiters",
    )
    ap.add_argument(
        "--retry-hosts",
        nargs="*",
        default=None,
        help="Only process these hosts (e.g. gallica.bnf.fr)",
    )
    args = ap.parse_args()

    if args.harvest_root is None:
        # Prefer sibling of jobs-root: .../latin-ms-workspace/computus_web_harvest
        cand = args.jobs_root.parent / "computus_web_harvest"
        if cand.is_dir():
            args.harvest_root = cand

    rows = load_queue(args.queue)
    if args.retry_hosts:
        hosts = set(args.retry_hosts)
        rows = [r for r in rows if r.get("host") in hosts]
    if args.limit > 0:
        rows = rows[: args.limit]

    args.jobs_root.mkdir(parents=True, exist_ok=True)
    log_root = (
        (args.harvest_root / "logs")
        if args.harvest_root
        else (args.jobs_root.parent / "computus_web_harvest" / "logs")
    )
    log_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    running: dict[str, subprocess.Popen] = {}
    # key -> {page_estimate, logf}
    run_meta: dict[str, dict[str, Any]] = {}

    def can_launch(host: str) -> bool:
        cap = HOST_CONCURRENCY.get(host, DEFAULT_HOST_CONCURRENCY)
        if cap <= 0:
            return False
        if len(running) >= args.global_concurrency:
            return False
        return active_for_host(running, host) < cap

    def mark_skip_done(jid: str, host: str, nimg: int, pe: int | None, reason: str) -> None:
        job = args.jobs_root / jid
        mark_done(
            job,
            nimg=nimg,
            reason=reason,
            min_images=args.min_images_done,
            page_estimate=pe,
            returncode=0,
            host=host,
            harvest_root=args.harvest_root,
        )

    def reap() -> None:
        done_keys = []
        for key, proc in list(running.items()):
            rc = proc.poll()
            if rc is None:
                continue
            host, jid = key.split("|", 1)
            meta = run_meta.pop(key, {})
            logf = meta.get("logf")
            if logf is not None:
                try:
                    logf.close()
                except Exception:
                    pass
            job = args.jobs_root / jid
            pe = meta.get("page_estimate")
            status = finalize_after_acquire(
                job,
                returncode=rc,
                min_images=args.min_images_done,
                page_estimate=pe,
                host=host,
                harvest_root=args.harvest_root,
            )
            nimg = count_images(job / "00_sources_chunks" / "full")
            print(
                f"[finished {status}] {jid} rc={rc} images={nimg}",
                flush=True,
            )
            results.append(
                {
                    "job_id": jid,
                    "host": host,
                    "returncode": rc,
                    "ms_status": status,
                    "n_images": nimg,
                }
            )
            done_keys.append(key)
        for key in done_keys:
            running.pop(key, None)

    idx = 0
    while idx < len(rows) or running:
        reap()
        launched = False
        while idx < len(rows) and len(running) < args.global_concurrency:
            row = rows[idx]
            host = row.get("host") or "unknown"
            if not can_launch(host):
                progressed = False
                for j in range(idx + 1, min(idx + 20, len(rows))):
                    if can_launch(rows[j].get("host") or "unknown"):
                        rows[idx], rows[j] = rows[j], rows[idx]
                        row = rows[idx]
                        host = row.get("host") or "unknown"
                        progressed = True
                        break
                if not progressed:
                    break
            jid = row["job_id"]
            job = args.jobs_root / jid
            img_dir = job / "00_sources_chunks" / "full"
            pe = row.get("page_estimate")
            try:
                pe_int = int(pe) if pe is not None else None
            except (TypeError, ValueError):
                pe_int = None
            nimg = count_images(img_dir)
            done_marker = (job / "status" / "acquire.DONE").is_file()
            pe_ok = pe_int is not None and pe_int > 0 and nimg >= max(
                args.min_images_done, int(0.9 * pe_int)
            )
            if (done_marker and nimg >= args.min_images_done) or pe_ok:
                print(f"[skip done] {jid} ({nimg} images)", flush=True)
                mark_skip_done(jid, host, nimg, pe_int, "already_on_disk")
                results.append(
                    {
                        "job_id": jid,
                        "host": host,
                        "returncode": 0,
                        "skipped": "done",
                        "ms_status": "done",
                        "n_images": nimg,
                    }
                )
                idx += 1
                continue
            if row.get("robots_allowed") is False:
                print(f"[skip robots] {jid}", flush=True)
                results.append(
                    {"job_id": jid, "host": host, "returncode": 0, "skipped": "robots"}
                )
                idx += 1
                continue
            if HOST_CONCURRENCY.get(host, DEFAULT_HOST_CONCURRENCY) <= 0:
                print(f"[skip host] {jid} host={host}", flush=True)
                results.append(
                    {
                        "job_id": jid,
                        "host": host,
                        "returncode": 0,
                        "skipped": "host_blocked",
                    }
                )
                idx += 1
                continue

            job.mkdir(parents=True, exist_ok=True)
            img_dir.mkdir(parents=True, exist_ok=True)
            (job / "status").mkdir(exist_ok=True)
            (job / "logs").mkdir(exist_ok=True)
            (job / "shelfmark.txt").write_text(
                str(row.get("shelfmark") or ""), encoding="utf-8"
            )
            (job / "source_url.txt").write_text(str(row["url"]), encoding="utf-8")
            meta = {
                "job_id": jid,
                "url": row["url"],
                "host": host,
                "record_id": row.get("record_id"),
                "rights": row.get("rights"),
                "material_role": row.get("material_role"),
                "page_estimate": pe_int,
            }
            row_flags = row.get("flags")
            if not row_flags:
                row_flags = strigil_flags(row["url"], page_estimate=pe_int)
            row_flags = with_parallel_workers(
                list(row_flags), row["url"], args.strigil_workers
            )
            cmd = strigil_cmd(
                args.python,
                row["url"],
                str(img_dir),
                page_estimate=pe_int,
                workers_default=args.strigil_workers,
                extra_flags=list(row_flags),
            )
            meta["flags"] = list(row_flags)
            meta["scraper"] = "strigil"
            meta["strigil_cmd"] = cmd
            (job / "acquire_meta.json").write_text(
                json.dumps(meta, indent=2) + "\n", encoding="utf-8"
            )

            print(f"[launch strigil] {jid} host={host} url={row['url'][:80]}", flush=True)
            if args.dry_run:
                results.append(
                    {
                        "job_id": jid,
                        "host": host,
                        "returncode": 0,
                        "skipped": "dry_run",
                    }
                )
                idx += 1
                continue

            logf = open(job / "logs" / "acquire_full.log", "ab")
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONPATH"] = str(args.strigil_dir) + (
                os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
            )
            proc = subprocess.Popen(
                cmd,
                cwd=str(args.strigil_dir),
                env=env,
                stdout=logf,
                stderr=subprocess.STDOUT,
            )
            (job / "status" / "acquire_full.pid").write_text(
                str(proc.pid), encoding="utf-8"
            )
            key = f"{host}|{jid}"
            running[key] = proc
            run_meta[key] = {"page_estimate": pe_int, "logf": logf}
            idx += 1
            launched = True
            if host == "gallica.bnf.fr":
                time.sleep(3.0)
            else:
                time.sleep(0.5)
        if not launched and running:
            time.sleep(5.0)
        elif not running and idx >= len(rows):
            break
        elif not launched and not running and idx < len(rows):
            skipped_any = False
            while idx < len(rows):
                host = rows[idx].get("host") or "unknown"
                if HOST_CONCURRENCY.get(host, DEFAULT_HOST_CONCURRENCY) <= 0:
                    print(
                        f"[skip host] {rows[idx]['job_id']} host={host}",
                        flush=True,
                    )
                    results.append(
                        {
                            "job_id": rows[idx]["job_id"],
                            "host": host,
                            "returncode": 0,
                            "skipped": "host_blocked",
                        }
                    )
                    idx += 1
                    skipped_any = True
                    continue
                break
            if not skipped_any:
                print(
                    f"[warn] cannot launch remaining {len(rows)-idx}; stopping",
                    flush=True,
                )
                break
        elif not launched:
            time.sleep(2.0)

    reap()
    out = log_root / f"acquire_results_{int(time.time())}.json"
    out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"[done] results={len(results)} → {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
