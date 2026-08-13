#!/usr/bin/env python3
"""Build a deduplicated computus source registry.

Unifies:
  - references/computus-library/computus_lat_ms-catalog.json (computus.lat, ~684)
  - references/computus-library/manifest.json (CitCA + local witnesses)
  - optional stylometry-r historical_cohort_decisions.csv (35-target cohort)

Outputs JSONL + summary under references/computus-library/web_harvest/.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "references" / "computus-library" / "web_harvest"


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    u = url.strip().rstrip(",")
    if not u:
        return None
    if u.startswith("//"):
        u = "https:" + u
    if not u.startswith("http"):
        return None
    return u


def split_urls(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for part in re.split(r"[\s,]+", str(raw)):
        u = normalize_url(part)
        if u and u not in out:
            out.append(u)
    return out


def host_of(url: str | None) -> str | None:
    if not url:
        return None
    return urllib.parse.urlparse(url).netloc.lower() or None


def shelfmark_key(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # collapse common shelfmark noise
    s = s.replace(" clm ", " clm ").replace(" lat ", " lat ")
    return s


def institution_hint(shelf: str) -> str:
    """First comma-separated place + collection fragment."""
    parts = [p.strip() for p in shelf.split(",") if p.strip()]
    return " ".join(parts[:2]).lower() if parts else shelf.lower()


def stable_id(prefix: str, key: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", key.lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return f"{prefix}_{s}"[:80]


def is_manifest(url: str) -> bool:
    low = url.lower().split("?")[0]
    return low.endswith("/manifest") or low.endswith("/manifest.json") or "manifest" in low


def classify_url(url: str) -> str:
    low = url.lower()
    if "archive.org" in low:
        return "archive_org"
    if is_manifest(url) or "iiif" in low:
        return "iiif"
    if any(
        h in low
        for h in (
            "gallica.bnf.fr",
            "digi.vatlib.it",
            "e-codices",
            "digitale-sammlungen",
            "bodleian",
            "bvmm.irht",
            "wellcomecollection",
            "themorgan.org",
            "bl.uk",
            "cudl.lib.cam",
            "manuscripta",
        )
    ):
        return "digitization_page"
    return "catalogue_or_other"


def empty_record(rid: str) -> dict[str, Any]:
    return {
        "id": rid,
        "aliases": [],
        "shelfmark": None,
        "display": None,
        "institution": None,
        "origin": None,
        "date": None,
        "sources": [],
        "candidate_urls": [],
        "iiif_urls": [],
        "digitization_urls": [],
        "archive_org_urls": [],
        "texts": [],
        "material_role": "direct_computus",
        "computus_evidence": None,
        "cohort_slug": None,
        "cohort_status": None,
        "acquisition": {
            "status": "pending",
            "confirmed_url": None,
            "access": "unknown",
            "rights": None,
            "robots_allowed": None,
            "page_estimate": None,
            "last_error": None,
            "downloaded_pages": 0,
            "job_dir": None,
        },
        "notes": [],
    }


def add_url(rec: dict[str, Any], url: str, provenance: str) -> None:
    kind = classify_url(url)
    bucket = {
        "iiif": "iiif_urls",
        "archive_org": "archive_org_urls",
        "digitization_page": "digitization_urls",
        "catalogue_or_other": "digitization_urls",
    }[kind]
    if url not in rec[bucket]:
        rec[bucket].append(url)
    if not any(c["url"] == url for c in rec["candidate_urls"]):
        rec["candidate_urls"].append(
            {
                "url": url,
                "kind": kind,
                "host": host_of(url),
                "provenance": provenance,
                "status": "unvalidated",
                "confidence": "high" if kind == "iiif" else "medium",
            }
        )


def merge_record(primary: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    for alias in other.get("aliases", []):
        if alias not in primary["aliases"]:
            primary["aliases"].append(alias)
    for field in ("shelfmark", "display", "institution", "origin", "date"):
        if not primary.get(field) and other.get(field):
            primary[field] = other[field]
    for field in ("texts", "sources", "notes"):
        for item in other.get(field) or []:
            if item not in primary[field]:
                primary[field].append(item)
    if other.get("computus_evidence") and not primary.get("computus_evidence"):
        primary["computus_evidence"] = other["computus_evidence"]
    if other.get("cohort_slug"):
        primary["cohort_slug"] = other["cohort_slug"]
        primary["cohort_status"] = other.get("cohort_status")
        primary["material_role"] = other.get("material_role", primary["material_role"])
    for c in other.get("candidate_urls", []):
        add_url(primary, c["url"], c.get("provenance", "merge"))
    return primary


def load_computus_lat(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for rec in data:
        msid = rec.get("MSID")
        shelf = (rec.get("Shelfmark") or "").strip()
        rid = f"clat_{msid}" if msid is not None else stable_id("clat", shelf)
        out = empty_record(rid)
        out["aliases"] = [rid, f"msid_{msid}"] if msid is not None else [rid]
        out["shelfmark"] = shelf
        out["display"] = shelf
        out["institution"] = institution_hint(shelf)
        out["sources"] = ["computus.lat"]
        if rec.get("Schriften"):
            out["texts"] = [t.strip() for t in str(rec["Schriften"]).split(",") if t.strip()]
            out["computus_evidence"] = rec["Schriften"]
        for url in split_urls(rec.get("IIIF")):
            add_url(out, url, "computus.lat:IIIF")
        for url in split_urls(rec.get("Digitalizations")):
            add_url(out, url, "computus.lat:Digitalizations")
        rows.append(out)
    return rows


def load_citca_manifest(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for ms in data.get("manuscripts", []):
        mid = ms["id"]
        out = empty_record(mid)
        out["aliases"] = [mid]
        out["display"] = ms.get("display") or mid
        out["shelfmark"] = ms.get("shelfmark") or ms.get("display")
        out["institution"] = ms.get("archive") or institution_hint(out["display"] or "")
        out["origin"] = ms.get("origin")
        out["date"] = ms.get("date_citca") or ms.get("date_computistical")
        out["sources"] = [ms.get("source") or "citca"]
        out["texts"] = list(ms.get("texts") or [])
        if out["texts"]:
            out["computus_evidence"] = "; ".join(out["texts"][:8])
        if ms.get("archive_ms_page"):
            add_url(out, normalize_url(ms["archive_ms_page"]) or ms["archive_ms_page"], "citca:archive_ms_page")
        if ms.get("local_image_root"):
            out["notes"].append(f"local_image_root={ms['local_image_root']}")
            out["acquisition"]["status"] = "local"
        if ms.get("notes"):
            out["notes"].append(ms["notes"])
        rows.append(out)
    return rows


# Full inclusive 35-target set from develop_historical_core.sh (material roles
# refined by historical_cohort_decisions.csv when present).
FULL_COHORT_SLUGS = [
    "sb_732_cod",
    "sb_878_cod",
    "sb_913_cod",
    "sb_110_cod",
    "sb_184_cod",
    "sb_248_cod",
    "sb_250_cod",
    "sb_682_cod",
    "nypl_computus_text_3",
    "bnf_lat_4860_cod",
    "bnf_lat_7418",
    "oxford_sjc_17",
    "pal_lat_1407",
    "wellcome_computistical_miscellany",
    "einsiedeln_sbe_029",
    "bl_royal_13_a_xi",
    "bsb_clm_4382",
    "bsb_clm_4376",
    "bl_harley_531",
    "wellcome_103",
    "wellcome_3",
    "bav_reg_lat_141_cu1",
    "bav_reg_lat_123",
    "bav_pal_lat_1354",
    "basel_ubb_f_vii_12",
    "basel_ubb_an_iv_18",
    "sb_251_1",
    "bl_cotton_vitellius_a_xii",
    "bl_royal_12_d_iv",
    "bnf_lat_894_cod",
    "bnf_lat_2796_cod",
    "bodleian_ms_bodl_309",
    "cambridge_cudl_ff_1_27",
    "bsb_clm_18158",
    "bsb_clm_14770",
]


def load_cohort(path: Path | None) -> list[dict[str, Any]]:
    audited: dict[str, dict[str, str]] = {}
    if path and path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            for rec in csv.DictReader(f):
                audited[rec["slug"]] = rec

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for slug in list(FULL_COHORT_SLUGS) + [
        s for s in audited if s not in FULL_COHORT_SLUGS
    ]:
        if slug in seen:
            continue
        seen.add(slug)
        rec = audited.get(slug, {})
        out = empty_record(slug)
        out["aliases"] = [slug]
        out["display"] = rec.get("manuscript") or slug.replace("_", " ")
        out["shelfmark"] = rec.get("manuscript") or slug
        out["institution"] = institution_hint(out["display"])
        out["origin"] = rec.get("origin")
        out["date"] = rec.get("date")
        out["sources"] = ["historical_cohort"]
        role = rec.get("material_role") or ""
        out["material_role"] = (
            "counterpoint" if "counterpoint" in role else "direct_computus"
        )
        out["computus_evidence"] = rec.get("computus_evidence")
        out["cohort_slug"] = slug
        out["cohort_status"] = rec.get("disposition") or "INCLUDE"
        if rec.get("rationale"):
            out["notes"].append(rec["rationale"])
        url = normalize_url(rec.get("citation_url"))
        if url:
            add_url(out, url, "cohort:citation_url")
        rows.append(out)
    return rows


def fuzzy_match_key(rec: dict[str, Any]) -> str:
    return shelfmark_key(rec.get("display") or rec.get("shelfmark") or rec["id"])


def build_union(
    clat: list[dict[str, Any]],
    citca: list[dict[str, Any]],
    cohort: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer longer/richer records; merge by shelfmark key when confident."""
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def ingest(items: list[dict[str, Any]], source_priority: int) -> None:
        for item in items:
            key = fuzzy_match_key(item)
            if not key:
                key = item["id"].lower()
            if key not in by_key:
                by_key[key] = item
                order.append(key)
                by_key[key]["_priority"] = source_priority
            else:
                existing = by_key[key]
                # Prefer keep longer catalog ids / richer candidates, merge fields
                if source_priority < existing.get("_priority", 99):
                    # lower priority number wins as base
                    merged = merge_record(item, existing)
                    merged["_priority"] = source_priority
                    by_key[key] = merged
                else:
                    by_key[key] = merge_record(existing, item)

    # Priority: cohort < citca/local < computus.lat for identity base, but all merge
    ingest(clat, 30)
    ingest(citca, 20)
    ingest(cohort, 10)

    out = []
    for key in order:
        rec = by_key[key]
        rec.pop("_priority", None)
        # acquisition status defaults
        if rec["acquisition"]["status"] == "pending":
            if rec["iiif_urls"]:
                rec["acquisition"]["status"] = "has_url"
            elif rec["digitization_urls"] or rec["archive_org_urls"]:
                rec["acquisition"]["status"] = "has_url"
            else:
                rec["acquisition"]["status"] = "needs_discovery"
        out.append(rec)
    return out


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    status = defaultdict(int)
    roles = defaultdict(int)
    hosts: dict[str, int] = defaultdict(int)
    with_iiif = with_dig = with_none = 0
    for r in records:
        status[r["acquisition"]["status"]] += 1
        roles[r["material_role"]] += 1
        if r["iiif_urls"]:
            with_iiif += 1
        elif r["digitization_urls"] or r["archive_org_urls"]:
            with_dig += 1
        else:
            with_none += 1
        for c in r["candidate_urls"]:
            if c.get("host"):
                hosts[c["host"]] += 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_records": len(records),
        "by_status": dict(status),
        "by_role": dict(roles),
        "with_iiif": with_iiif,
        "with_digitization_only": with_dig,
        "with_no_url": with_none,
        "top_hosts": dict(sorted(hosts.items(), key=lambda x: -x[1])[:30]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--clat",
        type=Path,
        default=REPO_ROOT / "references/computus-library/computus_lat_ms-catalog.json",
    )
    ap.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "references/computus-library/manifest.json",
    )
    ap.add_argument(
        "--cohort",
        type=Path,
        default=Path(
            "/Users/halxiii/Projects/stylometry-r/scripts/historical_cohort_decisions.csv"
        ),
    )
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    clat = load_computus_lat(args.clat) if args.clat.exists() else []
    citca = load_citca_manifest(args.manifest) if args.manifest.exists() else []
    cohort = load_cohort(args.cohort if args.cohort.exists() else None)
    records = build_union(clat, citca, cohort)
    summary = summarize(records)

    jsonl_path = args.out_dir / "union_registry.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Convenience snapshot
    (args.out_dir / "union_registry_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    # Also copy full array for easy inspection
    (args.out_dir / "union_registry.json").write_text(
        json.dumps(
            {
                "version": 1,
                "generated_at": summary["generated_at"],
                "summary": summary,
                "records": records,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Wrote {len(records)} records → {jsonl_path}\n"
        f"  with_iiif={summary['with_iiif']} "
        f"digitization_only={summary['with_digitization_only']} "
        f"no_url={summary['with_no_url']}\n"
        f"  roles={summary['by_role']} status={summary['by_status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
