#!/usr/bin/env python3
"""Coverage audit + human-readable report for the computus web harvest."""
from __future__ import annotations

import argparse
import json
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

IMG_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2", ".webp"}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def host_of(url: str | None) -> str:
    if not url:
        return ""
    return urllib.parse.urlparse(url).netloc.lower()


def dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def count_images(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(
        1
        for p in path.rglob("*")
        if p.is_file() and p.suffix.lower() in IMG_SUFFIXES
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", type=Path, required=True)
    ap.add_argument("--jobs-root", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument(
        "--queue",
        type=Path,
        action="append",
        default=[],
        help="Optional acquire queue JSONL(s) for queue↔disk join stats",
    )
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_jsonl(args.registry)
    status = Counter()
    roles = Counter()
    hosts_confirmed = Counter()
    rights = Counter()
    failures = Counter()
    institutions = Counter()
    adapter_provenance = Counter()
    cohort = []
    need_review = []
    blocked = []
    confirmed = []
    downloaded_recs = []
    no_url = []
    unavailable = []
    failed = []

    for r in rows:
        acq = r.get("acquisition") or {}
        st = acq.get("status") or "unknown"
        status[st] += 1
        roles[r.get("material_role") or "unknown"] += 1
        inst = (r.get("institution") or institution_from_display(r) or "unknown")[:80]
        institutions[inst] += 1
        if r.get("cohort_slug"):
            cohort.append(r)
        url = acq.get("confirmed_url")
        if url:
            hosts_confirmed[host_of(url)] += 1
        if st in ("confirmed", "downloaded") or url:
            confirmed.append(r)
        if st == "downloaded":
            downloaded_recs.append(r)
        if acq.get("rights"):
            rights[str(acq["rights"])[:120]] += 1
        if st == "access_blocked":
            blocked.append(r)
        if st in ("needs_review",):
            need_review.append(r)
        if st in ("url_failed", "download_failed"):
            failed.append(r)
            if acq.get("last_error"):
                failures[str(acq["last_error"])[:120]] += 1
        if st in ("needs_discovery", "not_digitized_unknown") and not (
            r.get("candidate_urls")
        ):
            no_url.append(r)
        if st in ("not_digitized_unknown", "needs_discovery"):
            unavailable.append(r)
        for c in r.get("candidate_urls") or []:
            prov = str(c.get("provenance") or "")
            if prov.startswith("adapter:"):
                adapter_provenance[prov] += 1
            if c.get("decision") in ("failed",) and c.get("error"):
                failures[str(c.get("error"))[:120]] += 1

    downloaded = 0
    page_total = 0
    storage_bytes = 0
    by_host_pages: dict[str, int] = defaultdict(int)
    by_host_bytes: dict[str, int] = defaultdict(int)
    job_index: dict[str, dict[str, Any]] = {}
    if args.jobs_root and args.jobs_root.is_dir():
        for job in args.jobs_root.iterdir():
            if not job.is_dir():
                continue
            img = job / "00_sources_chunks" / "full"
            n = count_images(img)
            if n <= 0:
                continue
            downloaded += 1
            page_total += n
            nbytes = dir_size_bytes(img)
            storage_bytes += nbytes
            url = ""
            suf = job / "source_url.txt"
            if suf.exists():
                url = suf.read_text(encoding="utf-8", errors="replace").strip()
            h = host_of(url) or "unknown"
            by_host_pages[h] += n
            by_host_bytes[h] += nbytes
            job_index[job.name] = {
                "images": n,
                "bytes": nbytes,
                "host": h,
                "url": url,
            }

    # Queue progress
    queue_stats = []
    for qpath in args.queue or []:
        if not qpath.is_file():
            continue
        qrows = load_jsonl(qpath)
        ge5 = ge1 = 0
        for row in qrows:
            jid = str(row.get("job_id") or "")
            info = job_index.get(jid)
            if not info:
                continue
            if info["images"] >= 5:
                ge5 += 1
            elif info["images"] >= 1:
                ge1 += 1
        queue_stats.append(
            {
                "queue": str(qpath),
                "n": len(qrows),
                "with_ge5_images": ge5,
                "with_1_4_images": ge1,
                "missing_or_empty": len(qrows) - ge5 - ge1,
            }
        )

    est_pages = 0
    for r in confirmed:
        pe = (r.get("acquisition") or {}).get("page_estimate")
        try:
            if pe is not None:
                est_pages += int(pe)
        except (TypeError, ValueError):
            pass

    coverage = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records": len(rows),
        "by_status": dict(status),
        "by_role": dict(roles),
        "n_confirmed": sum(1 for r in confirmed if (r.get("acquisition") or {}).get("confirmed_url")),
        "n_downloaded_status": len(downloaded_recs),
        "n_access_blocked": len(blocked),
        "n_needs_review": len(need_review),
        "n_url_failed": len(failed),
        "n_unavailable_or_undigitized": len(unavailable),
        "n_no_url": len(no_url),
        "n_cohort": len(cohort),
        "confirmed_hosts": dict(hosts_confirmed.most_common()),
        "top_institutions": dict(institutions.most_common(40)),
        "adapter_hits": dict(adapter_provenance.most_common()),
        "top_failures": dict(failures.most_common(30)),
        "top_rights": dict(rights.most_common(25)),
        "jobs_with_images": downloaded,
        "images_total": page_total,
        "storage_bytes": storage_bytes,
        "storage_gb": round(storage_bytes / (1024**3), 3),
        "estimated_confirmed_pages": est_pages,
        "images_by_host": dict(sorted(by_host_pages.items(), key=lambda x: -x[1])),
        "bytes_by_host": dict(sorted(by_host_bytes.items(), key=lambda x: -x[1])),
        "queue_progress": queue_stats,
    }
    (args.out_dir / "coverage.json").write_text(
        json.dumps(coverage, indent=2) + "\n", encoding="utf-8"
    )

    def write_list(name: str, items: list[dict[str, Any]]) -> None:
        out = []
        for r in items:
            acq = r.get("acquisition") or {}
            out.append(
                {
                    "id": r.get("id"),
                    "display": r.get("display"),
                    "institution": r.get("institution") or institution_from_display(r),
                    "material_role": r.get("material_role"),
                    "status": acq.get("status"),
                    "confirmed_url": acq.get("confirmed_url"),
                    "page_estimate": acq.get("page_estimate"),
                    "downloaded_pages": acq.get("downloaded_pages"),
                    "rights": acq.get("rights"),
                    "last_error": acq.get("last_error"),
                    "cohort_slug": r.get("cohort_slug"),
                    "job_dir": acq.get("job_dir"),
                }
            )
        (args.out_dir / name).write_text(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    write_list("confirmed.json", confirmed)
    write_list("downloaded.json", downloaded_recs)
    write_list("access_blocked.json", blocked)
    write_list("needs_review.json", need_review)
    write_list("url_failed.json", failed)
    write_list("unavailable.json", unavailable)
    write_list("no_url.json", no_url)
    write_list("cohort_crosswalk.json", cohort)

    # Institution/source table for manual review
    inst_table = []
    for inst, n in institutions.most_common():
        subset = [
            r
            for r in rows
            if (r.get("institution") or institution_from_display(r) or "unknown")[:80]
            == inst
        ]
        stc = Counter((r.get("acquisition") or {}).get("status") for r in subset)
        inst_table.append({"institution": inst, "n": n, "by_status": dict(stc)})
    (args.out_dir / "by_institution.json").write_text(
        json.dumps(inst_table, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        "# Computus Web Harvest Coverage Report",
        "",
        f"Generated: {coverage['generated_at']}",
        "",
        "## Summary",
        "",
        f"- Registry records: **{coverage['n_records']}**",
        f"- With confirmed URL: **{coverage['n_confirmed']}**",
        f"- Status `downloaded`: **{coverage['n_downloaded_status']}**",
        f"- Access blocked (robots/terms): **{coverage['n_access_blocked']}**",
        f"- Needs review: **{coverage['n_needs_review']}**",
        f"- URL failed: **{coverage['n_url_failed']}**",
        f"- Unavailable / not digitized (unknown): **{coverage['n_unavailable_or_undigitized']}**",
        f"- No candidate URL: **{coverage['n_no_url']}**",
        f"- Cohort crosswalk rows: **{coverage['n_cohort']}**",
        f"- Jobs with images on disk: **{coverage['jobs_with_images']}** "
        f"({coverage['images_total']} image files, ~{coverage['storage_gb']} GiB)",
        f"- Sum of confirmed page estimates: **{coverage['estimated_confirmed_pages']}**",
        "",
        "### Acquisition status",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    for k, v in status.most_common():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "### Material roles",
        "",
        "| Role | Count |",
        "|---|---:|",
    ]
    for k, v in roles.most_common():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "### Confirmed hosts",
        "",
        "| Host | Confirmed records |",
        "|---|---:|",
    ]
    for k, v in hosts_confirmed.most_common(25):
        lines.append(f"| {k} | {v} |")
    if by_host_pages:
        lines += [
            "",
            "### Downloaded images by host",
            "",
            "| Host | Image files | ~GiB |",
            "|---|---:|---:|",
        ]
        for k, v in sorted(by_host_pages.items(), key=lambda x: -x[1])[:25]:
            gb = by_host_bytes.get(k, 0) / (1024**3)
            lines.append(f"| {k or 'unknown'} | {v} | {gb:.3f} |")
    if queue_stats:
        lines += ["", "### Acquire queue progress", ""]
        for qs in queue_stats:
            lines.append(
                f"- `{Path(qs['queue']).name}`: {qs['with_ge5_images']}/{qs['n']} "
                f"with ≥5 images ({qs['with_1_4_images']} partial, "
                f"{qs['missing_or_empty']} empty/missing)"
            )
    if adapter_provenance:
        lines += [
            "",
            "### Discovery adapter hits",
            "",
            "| Adapter | Candidate count |",
            "|---|---:|",
        ]
        for k, v in adapter_provenance.most_common(20):
            lines.append(f"| `{k}` | {v} |")
    if rights:
        lines += [
            "",
            "### Rights / license statements (top)",
            "",
            "| Statement | Count |",
            "|---|---:|",
        ]
        for k, v in rights.most_common(15):
            safe = k.replace("|", "\\|")[:100]
            lines.append(f"| {safe} | {v} |")
    lines += [
        "",
        "### Top failure reasons",
        "",
        "| Reason | Count |",
        "|---|---:|",
    ]
    for k, v in failures.most_common(15):
        lines.append(f"| `{k}` | {v} |")
    lines += [
        "",
        "## Interpretation notes",
        "",
        "- Confirmed means a candidate URL was successfully probed (HTTP 200) and met the confirmation threshold (existing IIIF / high-confidence catalogue link).",
        "- Access-blocked records retain catalogue URLs but are not queued for image download under robots policy (e.g. Harvard).",
        "- Needs-review records have candidate pages but insufficient confirmation (ambiguous Archive.org hits, soft failures).",
        "- Counterpoints in the 35-target cohort remain labeled `counterpoint` and must not enter the direct-computus denominator.",
        "- Image acquisition is separate from HTR; generate a reviewed downstream queue only after sampling host adapters.",
        "",
        "## Companion machine-readable files",
        "",
        "- `coverage.json`",
        "- `confirmed.json` / `downloaded.json`",
        "- `access_blocked.json`",
        "- `needs_review.json` / `url_failed.json` / `unavailable.json` / `no_url.json`",
        "- `cohort_crosswalk.json`",
        "- `by_institution.json`",
        "- `repository_samples.json` (from validate_repository_samples.py)",
        "",
    ]
    (args.out_dir / "COVERAGE_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report → {args.out_dir / 'COVERAGE_REPORT.md'}")
    print(json.dumps({k: coverage[k] for k in (
        "n_records", "by_status", "jobs_with_images", "images_total", "storage_gb", "queue_progress"
    )}, indent=2))
    return 0


def institution_from_display(r: dict[str, Any]) -> str:
    disp = r.get("display") or r.get("shelfmark") or ""
    parts = [p.strip() for p in str(disp).split(",") if p.strip()]
    return ", ".join(parts[:2]) if parts else ""


if __name__ == "__main__":
    raise SystemExit(main())
