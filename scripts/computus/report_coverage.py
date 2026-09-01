#!/usr/bin/env python3
"""Write human/machine coverage reports for the computus web harvest."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def host_of(url: str | None) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = load_jsonl(args.registry)

    by_status = Counter()
    by_role = Counter()
    by_host = Counter()
    confirmed = downloaded = blocked = failed = need_review = no_url = 0
    pages = 0
    for r in rows:
        acq = r.get("acquisition") or {}
        st = acq.get("status") or "?"
        by_status[st] += 1
        by_role[r.get("material_role") or "?"] += 1
        h = host_of(acq.get("confirmed_url"))
        if h:
            by_host[h] += 1
        if st == "confirmed":
            confirmed += 1
        elif st == "downloaded":
            downloaded += 1
            pages += int(acq.get("downloaded_pages") or 0)
        elif st == "access_blocked":
            blocked += 1
        elif st in ("url_failed", "download_failed"):
            failed += 1
        elif st in ("needs_review", "needs_discovery"):
            need_review += 1
        elif st in ("not_digitized_unknown",) or (
            not r.get("candidate_urls") and st not in ("local", "downloaded")
        ):
            no_url += 1

    machine = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records": len(rows),
        "by_status": dict(by_status),
        "by_role": dict(by_role),
        "by_confirmed_host": dict(by_host.most_common()),
        "confirmed": confirmed,
        "downloaded": downloaded,
        "access_blocked": blocked,
        "failed": failed,
        "needs_review_or_discovery": need_review,
        "downloaded_pages_sum": pages,
    }
    (args.out_dir / "coverage_summary.json").write_text(
        json.dumps(machine, indent=2) + "\n", encoding="utf-8"
    )

    # Detailed CSVs-ish TSV
    tsv_path = args.out_dir / "coverage_by_record.tsv"
    with tsv_path.open("w", encoding="utf-8") as f:
        f.write(
            "id\tstatus\trole\tshelfmark\tconfirmed_url\thost\tpages\terror\tsources\n"
        )
        for r in sorted(rows, key=lambda x: x["id"]):
            acq = r.get("acquisition") or {}
            f.write(
                "\t".join(
                    [
                        r["id"],
                        str(acq.get("status") or ""),
                        str(r.get("material_role") or ""),
                        (r.get("shelfmark") or "").replace("\t", " "),
                        str(acq.get("confirmed_url") or ""),
                        host_of(acq.get("confirmed_url")),
                        str(acq.get("downloaded_pages") or acq.get("page_estimate") or ""),
                        (str(acq.get("last_error") or "")[:200]).replace("\t", " "),
                        "|".join(r.get("sources") or []),
                    ]
                )
                + "\n"
            )

    # Markdown report
    lines = [
        "# Computus web harvest coverage",
        "",
        f"Generated: {machine['generated_at']}",
        "",
        "## Counts",
        "",
        f"- Records: **{machine['n_records']}**",
        f"- Confirmed (not yet downloaded): **{confirmed}**",
        f"- Downloaded: **{downloaded}** ({pages} page files counted)",
        f"- Access blocked (robots/terms): **{blocked}**",
        f"- Failed URL/download: **{failed}**",
        f"- Needs review/discovery: **{need_review}**",
        "",
        "### By status",
        "",
        "| Status | n |",
        "|---|---:|",
    ]
    for k, v in by_status.most_common():
        lines.append(f"| `{k}` | {v} |")
    lines += [
        "",
        "### Confirmed hosts",
        "",
        "| Host | n |",
        "|---|---:|",
    ]
    for k, v in by_host.most_common(40):
        lines.append(f"| `{k}` | {v} |")

    # review queue
    review = [
        r
        for r in rows
        if (r.get("acquisition") or {}).get("status")
        in ("needs_review", "needs_discovery", "access_blocked", "url_failed", "download_failed")
    ]
    lines += [
        "",
        f"## Items needing human follow-up ({len(review)})",
        "",
    ]
    for r in review[:200]:
        acq = r.get("acquisition") or {}
        lines.append(
            f"- `{r['id']}` · {acq.get('status')} · {r.get('shelfmark') or r.get('display')} · "
            f"{acq.get('last_error') or acq.get('confirmed_url') or 'no url'}"
        )
    if len(review) > 200:
        lines.append(f"- … and {len(review) - 200} more (see coverage_by_record.tsv)")

    lines += [
        "",
        "## Notes",
        "",
        "- Confirmed requires successful probe of an existing catalogue/IIIF URL, or a high-confidence Archive.org hit.",
        "- Robots-disallowed hosts are metadata-only; no image download is attempted.",
        "- Counterpoints retain `material_role=counterpoint` and must not enter the direct-computus denominator.",
        "",
    ]
    (args.out_dir / "COVERAGE_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.out_dir / 'COVERAGE_REPORT.md'}")
    print(json.dumps(machine, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
