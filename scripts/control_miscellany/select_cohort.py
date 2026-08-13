#!/usr/bin/env python3
"""Select ~100 non-computus Latin miscellanies as a control harvest.

The 35-target computus lock is not extended. These books are scored later
against frozen CORE via --eval-dir. Do not pass them to lock_genre_core as
historical members.

Pool: e-codices catalogue hits for composite / Sammelband / miscellany /
florilegium, minus anything already in the computus union registry.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parents[1]
DEFAULT_REGISTRY = REPO / "references/computus-library/web_harvest/union_registry.jsonl"
DEFAULT_CACHE = REPO / "references/control-miscellany/cache"
DEFAULT_QUEUE = REPO / "references/control-miscellany/web_harvest/queues/acquire_queue.jsonl"
DEFAULT_CSV = REPO.parent / "stylometry-r/scripts/control_miscellany_decisions.csv"

SEARCH_TERMS = ("composite", "Sammelband", "Sammelhandschrift", "miscellany", "florilegium")
SEARCH_URL = "https://www.e-codices.unifr.ch/en/search/all"
IIIF_MANIFEST = "https://www.e-codices.unifr.ch/metadata/iiif/{lib}-{num}/manifest.json"

COMPUTUS_RE = re.compile(
    r"\b(computus|computistic|paschal|easter dates?|figuring easter|"
    r"de temporibus|de temporum ratione|helperic(?:us)?|"
    r"sacrobosco computus|easter tables?)\b",
    re.I,
)
MIXED_RE = re.compile(
    r"\b(composite|miscellany|sammelband|sammelhandschrift|florilegium|"
    r"among other|various texts|collection of|compiled|excerpts?)\b",
    re.I,
)
SINGLE_LITURGICAL_RE = re.compile(
    r"\b(gospel book|evangeliary|evangelistary|psalter|gradual|missal|"
    r"sacramentary|antiphonary|lectionary|breviary|bible|"
    r"lectiones nocturnales)\b",
    re.I,
)
LATIN_RE = re.compile(r"\blatin\b", re.I)
GERMAN_ONLY_RE = re.compile(r"\b(german|alemannic|middle high german)\b", re.I)
HEBREW_RE = re.compile(r"\bhebrew\b", re.I)
LATE_CENTURY_RE = re.compile(r"\b(16th|17th|18th|19th|20th)\s+century\b", re.I)
EARLY_CENTURY_RE = re.compile(
    r"\b(8th|9th|10th|11th|12th|13th|14th|15th)\s+century\b", re.I
)
OPTION_RE = re.compile(
    r'option value="https://www\.e-codices\.unifr\.ch/en/searchresult/list/one/([^"/]+)/([^"]+)"'
)
IIIF_ID_RE = re.compile(r"/iiif/(csg|sbe|ubb|bbb|bke|zbz|kbt)-([^/]+)/")

PREFERRED_LIBS = ("csg", "sbe", "ubb", "bbb")
USER_AGENT = "transcription-shell-control-cohort/0.1 (research; non-computus miscellany harvest)"

_SSL = ssl._create_unverified_context()


def fetch(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
        return resp.read()


def parse_search_ids(html: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for lib, num in OPTION_RE.findall(html):
        out.append((lib.lower(), num))
    return out


def search_page_count(html: str) -> int:
    m = re.search(r"<strong>([\d,]+)</strong>\s*documents found", html)
    if not m:
        return 0
    return int(m.group(1).replace(",", ""))


def computus_ecodices_ids(registry_path: Path) -> set[tuple[str, str]]:
    ids: set[tuple[str, str]] = set()
    if not registry_path.is_file():
        return ids
    with registry_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            blobs = list(rec.get("iiif_urls") or [])
            blobs.extend(rec.get("digitization_urls") or [])
            for c in rec.get("candidate_urls") or []:
                blobs.append(c.get("url") or "")
            for u in blobs:
                m = IIIF_ID_RE.search(str(u or ""))
                if m:
                    ids.add((m.group(1), m.group(2)))
    return ids


def meta_map(metadata: list[dict[str, Any]] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in metadata or []:
        lab = str(row.get("label") or "").strip()
        val = row.get("value")
        if isinstance(val, list):
            val = "; ".join(str(v) for v in val)
        out[lab] = str(val or "").strip()
    return out


def description_en(manifest: dict[str, Any]) -> str:
    desc = manifest.get("description")
    if isinstance(desc, str):
        return desc
    if isinstance(desc, list):
        for item in desc:
            if isinstance(item, dict) and item.get("@language") == "en":
                return str(item.get("@value") or "")
            if isinstance(item, str):
                return item
    return ""


def classify_record(meta: dict[str, str], description: str) -> dict[str, Any]:
    title = meta.get("Title (English)") or meta.get("Title") or ""
    summary = meta.get("Summary (English)") or description or ""
    lang = meta.get("Text Language") or ""
    century = meta.get("Century") or meta.get("Date of Origin (English)") or ""
    dtype = meta.get("Document Type") or ""
    blob = " ".join([title, summary, lang, century, dtype])

    reasons: list[str] = []
    if COMPUTUS_RE.search(blob):
        reasons.append("computus_content")
    if not LATIN_RE.search(lang or blob):
        reasons.append("not_latin")
    if HEBREW_RE.search(lang) and not LATIN_RE.search(lang):
        reasons.append("hebrew")
    if GERMAN_ONLY_RE.search(lang) and not LATIN_RE.search(lang):
        reasons.append("vernacular")
    if LATE_CENTURY_RE.search(century) and not EARLY_CENTURY_RE.search(century):
        reasons.append("post_medieval")
    if dtype.lower() == "fragment":
        reasons.append("fragment")
    if SINGLE_LITURGICAL_RE.search(title):
        reasons.append("single_liturgical")

    mixed = bool(MIXED_RE.search(blob))
    if not mixed:
        reasons.append("not_mixed")

    pages = None
    raw_pages = meta.get("Number of Pages") or ""
    m_pages = re.search(r"\d+", raw_pages.replace(",", ""))
    if m_pages:
        pages = int(m_pages.group(0))
    if pages is not None and pages < 20:
        reasons.append("too_short")

    ok = not reasons
    return {
        "ok": ok,
        "reasons": reasons,
        "mixed": mixed,
        "title": title,
        "summary": summary[:800],
        "language": lang,
        "century": century,
        "pages": pages,
        "origin": meta.get("Place of Origin (English)") or "",
        "date": meta.get("Date of Origin (English)") or "",
    }


def slug_for(lib: str, num: str) -> str:
    n = re.sub(r"[^a-z0-9]+", "_", num.lower()).strip("_")
    return f"ctrl_{lib}_{n}"[:60]


def shelfmark_for(lib: str, num: str, meta: dict[str, str]) -> str:
    sm = meta.get("Shelfmark") or num
    loc = meta.get("Location") or ""
    coll = meta.get("Collection Name") or ""
    if loc and coll:
        return f"{loc}, {coll}, {sm}"
    return sm


def library_rank(lib: str) -> int:
    try:
        return PREFERRED_LIBS.index(lib)
    except ValueError:
        return len(PREFERRED_LIBS)


def collect_search_ids(terms: tuple[str, ...] = SEARCH_TERMS, *, cache_dir: Path | None = None) -> list[tuple[str, str]]:
    seen: dict[tuple[str, str], None] = {}
    for term in terms:
        page = 1
        total = None
        while True:
            url = f"{SEARCH_URL}?sQueryString={urllib.parse.quote(term)}&iCurrentPage={page}"
            cache_path = None
            html = None
            if cache_dir is not None:
                cache_path = cache_dir / f"search_{term}_{page}.html"
                if cache_path.is_file():
                    html = cache_path.read_text(encoding="utf-8", errors="replace")
            if html is None:
                html = fetch(url).decode("utf-8", "replace")
                if cache_path is not None:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(html, encoding="utf-8")
            if total is None:
                total = search_page_count(html)
            for pair in parse_search_ids(html):
                seen.setdefault(pair)
            if page * 100 >= max(total, 1) or not parse_search_ids(html):
                break
            page += 1
            if page > 20:
                break
    return list(seen)


def extract_manifest_meta(manifest: dict[str, Any]) -> dict[str, Any]:
    meta = meta_map(manifest.get("metadata"))
    return {
        "label": manifest.get("label") or "",
        "description": description_en(manifest),
        "metadata": meta,
        "related": manifest.get("related") or "",
    }


def load_or_fetch_meta(lib: str, num: str, cache_dir: Path) -> dict[str, Any] | None:
    cache = cache_dir / "iiif_meta" / f"{lib}-{num}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    url = IIIF_MANIFEST.format(lib=lib, num=num)
    try:
        raw = json.loads(fetch(url).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — network/parse; skip candidate
        return {"_error": str(exc)}
    slim = extract_manifest_meta(raw)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
    return slim


def select_cohort(
    candidates: list[tuple[str, str]],
    *,
    exclude: set[tuple[str, str]],
    cache_dir: Path,
    n: int = 100,
    fetch_meta: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    ranked = sorted(candidates, key=lambda p: (library_rank(p[0]), p[0], p[1]))
    chosen: list[dict[str, Any]] = []
    skipped = defaultdict(int)
    for lib, num in ranked:
        if (lib, num) in exclude:
            skipped["in_computus_registry"] += 1
            continue
        if not fetch_meta:
            chosen.append(
                {
                    "lib": lib,
                    "num": num,
                    "slug": slug_for(lib, num),
                    "manifest_url": IIIF_MANIFEST.format(lib=lib, num=num),
                    "ok": True,
                    "reasons": [],
                    "title": "",
                    "summary": "",
                    "language": "",
                    "century": "",
                    "pages": None,
                    "origin": "",
                    "date": "",
                    "shelfmark": f"{lib}-{num}",
                }
            )
            if len(chosen) >= n:
                break
            continue
        slim = load_or_fetch_meta(lib, num, cache_dir)
        if not slim or slim.get("_error"):
            skipped["fetch_failed"] += 1
            continue
        verdict = classify_record(slim.get("metadata") or {}, slim.get("description") or "")
        if not verdict["ok"]:
            for r in verdict["reasons"]:
                skipped[r] += 1
            continue
        row = {
            "lib": lib,
            "num": num,
            "slug": slug_for(lib, num),
            "manifest_url": IIIF_MANIFEST.format(lib=lib, num=num),
            "shelfmark": shelfmark_for(lib, num, slim.get("metadata") or {}),
            "related": slim.get("related") or "",
            **verdict,
        }
        chosen.append(row)
        if len(chosen) >= n:
            break
    return chosen, dict(skipped)


def write_decisions_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "slug",
        "manuscript",
        "date",
        "origin",
        "disposition",
        "material_role",
        "computus_evidence",
        "source_status",
        "rationale",
        "citation_url",
        "lib",
        "ecodices_id",
        "language",
        "pages",
        "title",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "slug": r["slug"],
                    "manuscript": r.get("shelfmark") or f"{r['lib']}-{r['num']}",
                    "date": r.get("date") or "",
                    "origin": r.get("origin") or "",
                    "disposition": "INCLUDE",
                    "material_role": "control_noncomputus",
                    "computus_evidence": "none; excluded from computus registry and catalogue computus terms",
                    "source_status": "e-codices IIIF; harvest pending",
                    "rationale": (r.get("title") or r.get("summary") or "e-codices composite/miscellany")[:400],
                    "citation_url": r.get("manifest_url") or "",
                    "lib": r["lib"],
                    "ecodices_id": r["num"],
                    "language": r.get("language") or "",
                    "pages": r.get("pages") or "",
                    "title": r.get("title") or "",
                }
            )


def write_acquire_queue(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO / "scripts/computus"))
    from strigil_flags import strigil_flags  # noqa: E402

    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            url = r["manifest_url"]
            rec = {
                "job_id": r["slug"],
                "record_id": r["slug"],
                "url": url,
                "flags": strigil_flags(url, page_estimate=r.get("pages")),
                "scraper": "strigil",
                "shelfmark": r.get("shelfmark") or "",
                "host": urlparse(url).netloc,
                "material_role": "control_noncomputus",
                "page_estimate": r.get("pages"),
                "reason": "control_noncomputus_ecodices",
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--out-csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--out-queue", type=Path, default=DEFAULT_QUEUE)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--ids-only", action="store_true", help="Skip IIIF metadata fetch")
    args = ap.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    print("[control] paging e-codices search", flush=True)
    ids = collect_search_ids(cache_dir=args.cache_dir)
    exclude = computus_ecodices_ids(args.registry)
    print(f"[control] search pool {len(ids)}; computus-registry overlap filter {len(exclude)}", flush=True)
    rows, skipped = select_cohort(
        ids,
        exclude=exclude,
        cache_dir=args.cache_dir,
        n=args.n,
        fetch_meta=not args.ids_only,
    )
    write_decisions_csv(rows, args.out_csv)
    write_acquire_queue(rows, args.out_queue)
    libs = defaultdict(int)
    for r in rows:
        libs[r["lib"]] += 1
    print(f"[control] selected {len(rows)} -> {args.out_csv}")
    print(f"[control] acquire queue -> {args.out_queue}")
    print("[control] libraries", dict(libs))
    print("[control] skipped", skipped)
    return 0 if len(rows) >= min(args.n, 1) else 1


if __name__ == "__main__":
    raise SystemExit(main())
