#!/usr/bin/env python3
"""Build a structured acquire queue (JSONL) from a discovered/validated registry.

Replaces fragile positional TSV so empty flags cannot shift shelfmark into args.
Default: confirmed sources only. Optional: needs_review / ambiguous candidates.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strigil_flags import strigil_flags  # noqa: E402

# Strigil cannot usefully scrape bare catalogue *search* endpoints.
SKIP_KINDS = frozenset({"catalogue_search", "catalogue_api"})

KIND_RANK = {
    "iiif": 0,
    "digitization_page": 1,
    "archive_org": 2,
    "catalogue_page": 3,
    "catalogue_or_other": 4,
}
CONF_RANK = {"high": 0, "medium": 1, "low": 2}
DEC_RANK = {"confirmed": 0, "ambiguous": 1, "ok": 1, "failed": 2, None: 3}


def job_id(rec: dict[str, Any]) -> str:
    if rec.get("cohort_slug"):
        return str(rec["cohort_slug"])[:60]
    base = rec.get("id") or "ms"
    s = re.sub(r"[^a-z0-9]+", "_", str(base).lower())
    return re.sub(r"_+", "_", s).strip("_")[:60]


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


def candidate_score(c: dict[str, Any]) -> tuple:
    """Lower is better."""
    url = (c.get("final_url") or c.get("url") or "").lower()
    kind = c.get("kind") or ""
    kind_pen = 50 if kind in SKIP_KINDS else 0
    robots_pen = 100 if c.get("robots_allowed") is False else 0
    status_pen = 0 if c.get("status") == "ok" else (5 if c.get("status") == "failed" else 3)
    return (
        robots_pen + kind_pen,
        KIND_RANK.get(kind, 9),
        DEC_RANK.get(c.get("decision"), 3),
        CONF_RANK.get(c.get("confidence") or "low", 3),
        status_pen,
        0 if c.get("iiif") else 1,
        0 if "manifest" in url else 1,
    )


def pick_best_url(
    rec: dict[str, Any],
    *,
    allow_failed: bool = True,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Return (url, reason, candidate) for the best tryable source."""
    usable: list[dict[str, Any]] = []
    for c in rec.get("candidate_urls") or []:
        url = c.get("final_url") or c.get("url")
        if not url or not str(url).startswith("http"):
            continue
        if c.get("robots_allowed") is False:
            continue
        kind = c.get("kind") or ""
        if kind in SKIP_KINDS:
            continue
        if not allow_failed:
            st = c.get("http_status")
            if st is not None and int(st) >= 400:
                continue
            if c.get("decision") == "failed" and c.get("status") != "ok":
                continue
        usable.append(c)
    if not usable:
        return None, None, None
    usable.sort(key=candidate_score)
    best = usable[0]
    url = best.get("final_url") or best.get("url")
    reason = f"best_{best.get('decision') or best.get('status') or 'candidate'}"
    return str(url), reason, best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--include-ambiguous",
        action="store_true",
        help="Also enqueue needs_review candidates that returned HTTP 200",
    )
    ap.add_argument(
        "--needs-review-all",
        action="store_true",
        help="Enqueue every needs_review record using its best tryable candidate URL",
    )
    ap.add_argument(
        "--only-status",
        nargs="*",
        default=None,
        help="If set, only records with these acquisition.status values",
    )
    ap.add_argument(
        "--no-failed-candidates",
        action="store_true",
        help="Do not pick URLs that previously HTTP-failed during discovery",
    )
    args = ap.parse_args()

    rows_out: list[dict[str, Any]] = []
    skipped_no_url = 0
    with args.registry.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            acq = rec.get("acquisition") or {}
            st = acq.get("status") or ""

            if args.only_status and st not in args.only_status:
                continue

            if acq.get("robots_allowed") is False or st == "access_blocked":
                continue

            url = acq.get("confirmed_url")
            reason = "confirmed"
            pe = acq.get("page_estimate")
            rights = acq.get("rights")
            robots = acq.get("robots_allowed")

            if not url and args.needs_review_all and st == "needs_review":
                url, reason, best = pick_best_url(
                    rec, allow_failed=not args.no_failed_candidates
                )
                if best:
                    pe = pe or best.get("page_count")
                    rights = rights or best.get("rights")
                    robots = best.get("robots_allowed") if robots is None else robots
                    reason = f"needs_review_{reason}"

            if not url and args.include_ambiguous and not args.needs_review_all:
                for c in rec.get("candidate_urls") or []:
                    if c.get("status") == "ok" and c.get("decision") in (
                        "confirmed",
                        "ambiguous",
                    ):
                        if c.get("robots_allowed") is False:
                            continue
                        if (c.get("kind") or "") in SKIP_KINDS:
                            continue
                        url = c.get("final_url") or c.get("url")
                        reason = "ambiguous_ok"
                        pe = pe or c.get("page_count")
                        rights = rights or c.get("rights")
                        robots = c.get("robots_allowed") if robots is None else robots
                        break

            # default confirmed-only path still needs status filter when only-status unset
            if not args.needs_review_all and not args.include_ambiguous:
                if st and st not in ("confirmed", "downloaded", "has_url", ""):
                    if not url:
                        continue

            if not url:
                if args.needs_review_all and st == "needs_review":
                    skipped_no_url += 1
                continue

            try:
                pe_int = int(pe) if pe is not None else None
            except (TypeError, ValueError):
                pe_int = None

            flags = strigil_flags(str(url), page_estimate=pe_int)
            rows_out.append(
                {
                    "job_id": job_id(rec),
                    "record_id": rec.get("id"),
                    "url": str(url),
                    "flags": flags,
                    "scraper": "strigil",
                    "shelfmark": rec.get("display") or rec.get("shelfmark") or "",
                    "host": host_of(str(url)),
                    "material_role": rec.get("material_role"),
                    "page_estimate": pe_int,
                    "rights": rights,
                    "reason": reason,
                    "robots_allowed": robots,
                    "acquisition_status": st,
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # de-dupe by job_id (keep first)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows_out:
        jid = row["job_id"]
        if jid in seen:
            continue
        seen.add(jid)
        deduped.append(row)

    with args.out.open("w", encoding="utf-8") as f:
        for row in deduped:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(
        f"Wrote {len(deduped)} queue rows → {args.out}"
        + (f" (skipped needs_review no-url={skipped_no_url})" if skipped_no_url else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
