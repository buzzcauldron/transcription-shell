#!/usr/bin/env python3
"""Acquire confirmed manuscript scans into a harvest tree.

Uses strigil CLI when available. JSONL queue; never feeds free-text shelfmarks
as CLI flags. Respects robots_allowed and confirmed_url only.

Environment:
  HARVEST_ROOT   default: references/computus-library/web_harvest
  STRIGIL_PY     python with strigil installed
  STRIGIL_DIR    path containing strigil package
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strigil_flags import strigil_cmd, strigil_flags  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def strigil_flags_for(url: str, page_estimate: int | None = None) -> list[str]:
    """Safe structured flags only (no free text)."""
    return strigil_flags(url, page_estimate=page_estimate)


def count_images(out_dir: Path) -> int:
    if not out_dir.is_dir():
        return 0
    n = 0
    for p in out_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in {
            ".jpg",
            ".jpeg",
            ".png",
            ".tif",
            ".tiff",
            ".jp2",
            ".webp",
        }:
            n += 1
    return n


def run_strigil(
    url: str,
    out_dir: Path,
    *,
    strigil_py: str,
    strigil_dir: Path | None,
    dry_run: bool,
) -> tuple[int, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = strigil_cmd(strigil_py, url, str(out_dir))
    log_path = out_dir / "acquire.log"
    if dry_run:
        log_path.write_text("DRY_RUN " + " ".join(cmd) + "\n", encoding="utf-8")
        return 0, "dry_run"
    env = os.environ.copy()
    if strigil_dir:
        env["PYTHONPATH"] = str(strigil_dir) + os.pathsep + env.get("PYTHONPATH", "")
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# {now()}\n# {' '.join(cmd)}\n")
        log.flush()
        proc = subprocess.run(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(strigil_dir) if strigil_dir else None,
        )
    return proc.returncode, str(log_path)


def eligible(rec: dict[str, Any]) -> bool:
    acq = rec.get("acquisition") or {}
    if acq.get("status") in ("downloaded", "local"):
        return False
    if acq.get("robots_allowed") is False:
        return False
    if acq.get("access") in ("robots_blocked",):
        return False
    if acq.get("status") != "confirmed":
        return False
    if not acq.get("confirmed_url"):
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--registry",
        type=Path,
        required=True,
        help="Validated/discovered union registry JSONL",
    )
    ap.add_argument(
        "--harvest-root",
        type=Path,
        default=None,
        help="Root for per-ms image dirs (default: registry parent / acquisitions)",
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=1.0, help="Seconds between manuscripts")
    ap.add_argument(
        "--strigil-py",
        default=os.environ.get("STRIGIL_PY", sys.executable),
    )
    ap.add_argument(
        "--strigil-dir",
        type=Path,
        default=Path(os.environ["STRIGIL_DIR"]) if os.environ.get("STRIGIL_DIR") else None,
    )
    ap.add_argument(
        "--host-sleep",
        type=float,
        default=3.0,
        help="Extra delay after Gallica acquire",
    )
    args = ap.parse_args()

    harvest_root = args.harvest_root or (args.registry.parent / "acquisitions")
    harvest_root.mkdir(parents=True, exist_ok=True)
    rows = load_jsonl(args.registry)
    queue = [r for r in rows if eligible(r)]
    if args.limit > 0:
        queue = queue[: args.limit]

    print(f"[harvest] eligible={len(queue)} / total={len(rows)} root={harvest_root}", file=sys.stderr)

    # Emit structured queue for audit
    queue_path = harvest_root / "acquire_queue.jsonl"
    with queue_path.open("w", encoding="utf-8") as f:
        for rec in queue:
            url = rec["acquisition"]["confirmed_url"]
            f.write(
                json.dumps(
                    {
                        "id": rec["id"],
                        "url": url,
                        "flags": strigil_flags_for(url),
                        "shelfmark": rec.get("shelfmark"),
                        "role": rec.get("material_role"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    by_id = {r["id"]: r for r in rows}
    hosts = defaultdict(int)
    ok = fail = skip = 0
    for n, rec in enumerate(queue, 1):
        rid = rec["id"]
        url = rec["acquisition"]["confirmed_url"]
        host = urlparse(url).netloc.lower()
        out_dir = harvest_root / "images" / rid
        meta_dir = harvest_root / "meta" / rid
        meta_dir.mkdir(parents=True, exist_ok=True)
        # resume
        existing = count_images(out_dir)
        if existing >= 5 and not args.dry_run:
            print(f"[skip done] {rid} ({existing} images)", file=sys.stderr)
            rec["acquisition"]["status"] = "downloaded"
            rec["acquisition"]["downloaded_pages"] = existing
            rec["acquisition"]["job_dir"] = str(out_dir)
            by_id[rid] = rec
            skip += 1
            continue
        print(f"[acquire {n}/{len(queue)}] {rid} → {host}", file=sys.stderr)
        (meta_dir / "source_url.txt").write_text(url + "\n", encoding="utf-8")
        (meta_dir / "record.json").write_text(
            json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        # Save manifest snapshot if IIIF
        try:
            import httpx

            if "manifest" in url.lower() or "iiif" in url.lower():
                r = httpx.get(url, timeout=60.0, follow_redirects=True, headers={"User-Agent": "transcription-shell-computus-harvest/1.0"})
                if r.status_code < 400:
                    (meta_dir / "manifest.json").write_bytes(r.content)
                    rec["acquisition"]["rights"] = rec["acquisition"].get("rights")
        except Exception as exc:
            (meta_dir / "manifest_fetch_error.txt").write_text(str(exc), encoding="utf-8")

        code, logp = run_strigil(
            url,
            out_dir,
            strigil_py=args.strigil_py,
            strigil_dir=args.strigil_dir,
            dry_run=args.dry_run,
        )
        pages = count_images(out_dir)
        rec["acquisition"]["downloaded_pages"] = pages
        rec["acquisition"]["job_dir"] = str(out_dir)
        if code == 0 and (pages > 0 or args.dry_run):
            rec["acquisition"]["status"] = "downloaded" if not args.dry_run else "confirmed"
            rec["acquisition"]["last_error"] = None
            ok += 1
        else:
            rec["acquisition"]["status"] = "download_failed"
            rec["acquisition"]["last_error"] = f"strigil_exit={code} pages={pages} log={logp}"
            fail += 1
        by_id[rid] = rec
        hosts[host] += 1
        # periodic checkpoint
        if n % 10 == 0:
            write_jsonl(args.registry.with_name("union_registry_harvest_state.jsonl"), list(by_id.values()))
        sleep = args.sleep
        if "gallica" in host:
            sleep = max(sleep, args.host_sleep)
        time.sleep(sleep)

    final_rows = list(by_id.values())
    state_path = harvest_root / "union_registry_harvest_state.jsonl"
    write_jsonl(state_path, final_rows)
    # also write adjacent to registry
    write_jsonl(args.registry.with_name("union_registry_harvest_state.jsonl"), final_rows)

    summary = {
        "generated_at": now(),
        "eligible": len(queue),
        "ok": ok,
        "fail": fail,
        "skipped_existing": skip,
        "hosts": dict(hosts),
        "harvest_root": str(harvest_root),
    }
    (harvest_root / "harvest_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
