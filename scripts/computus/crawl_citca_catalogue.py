#!/usr/bin/env python3
"""Crawl Computus in the Carolingian Age (CitCA) manuscript catalogue into a JSON library.

Source: https://computus.huma-num.fr/mss/list

Merges with local witnesses from references/computus-manuscript-map.md and writes
references/computus-library/manifest.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

LIST_URL = "https://computus.huma-num.fr/mss/list"
BASE_MS_URL = "https://computus.huma-num.fr/mss/"
REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "references" / "computus-library"

ARCHIVE_LINK_HINTS = (
    "gallica.bnf.fr",
    "ark:/",
    "digi.vatlib.it",
    "mdz-nbn",
    "hathitrust",
    "wellcomecollection.org",
    "morgan.org/manuscript",
    "bl.uk/manuscripts",
    "archive.org",
    "e-codices",
    "manuscripta.at",
    "stiftsbibliothek",
    "ambrosiana",
    "innovatingknowledge.nl",
    "mirabileweb.it",
    "badw.de",
    "elmss.nuigalway.ie",
    "csic.es",
    "bezirk",
)

# Local witnesses (not in CitCA catalogue) — merged into unified library.
LOCAL_WITNESSES: list[dict[str, Any]] = [
    {
        "id": "tours_bm_746",
        "source": "local",
        "display": "Tours, Bibliothèque municipale, MS 746",
        "archive": "Bibliothèque municipale de Tours",
        "shelfmark": "MS 746",
        "origin": "Western France",
        "local_image_root": (
            "~/Library/CloudStorage/Dropbox/Seth/Cornell/"
            "Spring 2018/Vatican Film Library Fellowship Summer 2018/"
            "Bibliotheque Municipale De Tours 746"
        ),
        "doc_type": "computus_medieval_latin",
        "pipeline_status": "batch_transcription_in_progress",
        "bib_keys": [],
        "notes": "Primary transcription-shell test corpus; not indexed on computus.huma-num.fr.",
    },
    {
        "id": "morgan_m925",
        "source": "local",
        "display": "New York, Morgan Library, MS M.925",
        "archive": "The Morgan Library & Museum",
        "shelfmark": "M.925",
        "archive_ms_page": "https://www.themorgan.org/manuscript/160011",
        "strigil_acquire": True,
        "bib_keys": ["ComputusCollectionMS"],
        "doc_type": "computus_medieval_latin",
    },
    {
        "id": "bl_harley_3667",
        "source": "local",
        "display": "London, British Library, Harley MS 3667",
        "archive": "British Library",
        "shelfmark": "Harley MS 3667",
        "archive_ms_page": "https://www.bl.uk/collection-items/byrhtferths-computus",
        "strigil_acquire": True,
        "bib_keys": ["Computus"],
        "doc_type": "computus_medieval_latin",
        "notes": "Byrhtferth Enchiridion / computus diagram.",
    },
    {
        "id": "oxford_sjc_17",
        "source": "local",
        "display": "Oxford, St John's College, MS 17 (Thorney Computus)",
        "archive": "St John's College, Oxford",
        "shelfmark": "MS 17",
        "archive_ms_page": (
            "http://archive.org/details/TheByrhtferthsManuscriptms17SaintJohnsCollegeOxford"
        ),
        "strigil_acquire": True,
        "bib_keys": ["themonkbyrhtferthByrhtferthsManuscriptMS1111"],
        "doc_type": "computus_medieval_latin",
    },
    {
        "id": "cambridge_sjc_a22",
        "source": "local",
        "display": "Cambridge, St John's College, MS A.22 (Reading Computus)",
        "archive": "St John's College, Cambridge",
        "shelfmark": "MS A.22",
        "bib_keys": ["lawrence-mathersReadingComputusManuscriptSt"],
        "doc_type": "computus_medieval_latin",
    },
    {
        "id": "wellcome_computistical_miscellany",
        "source": "local",
        "display": "Wellcome Collection, Computistical miscellany",
        "archive": "Wellcome Collection",
        "shelfmark": "x3knvt2r",
        "archive_ms_page": "https://wellcomecollection.org/works/x3knvt2r",
        "strigil_acquire": True,
        "bib_keys": ["ComputisticalMiscellany"],
        "doc_type": "computus_medieval_latin",
        "texts": [
            "John of Erfurt, Computus chirometralis minor (ff. 1r–8r)",
            "Computus chirometralis maior (ff. 8r–16r)",
            "Peter of Dacia, Tabulae cum explicationibus (ff. 17v–18r)",
            "Computus judaicus (ff. 19v–22v)",
        ],
    },
    {
        "id": "nypl_computus_text_3",
        "source": "local",
        "display": "NYPL Digital Collections, Computus Text 3",
        "archive": "New York Public Library",
        "archive_ms_page": "https://digitalcollections.nypl.org/",
        "bib_keys": ["ComputusText3"],
        "notes": "Resolve exact item URL in NYPL before strigil acquire.",
    },
]


def list_slugs(client: httpx.Client) -> list[str]:
    r = client.get(LIST_URL)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    slugs: list[str] = []
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if "/mss/" not in h or "list" in h or "archive=" in h:
            continue
        if h.startswith("/mss/"):
            slug = h.split("/mss/")[1].strip("/").split("?")[0]
        else:
            m = re.search(r"/mss/([^/?#]+)", h)
            slug = m.group(1) if m else ""
        if slug and slug not in slugs:
            slugs.append(slug)
    return sorted(slugs)


def _field(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else None


def parse_ms_page(html: str, slug: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)
    url = BASE_MS_URL + slug

    archive = shelfmark = None
    for li in soup.find_all("li"):
        t = li.get_text(" ", strip=True)
        if t.startswith("Archive:") and not t.startswith("Archive Ms"):
            archive = t.split(":", 1)[1].strip()
        elif re.match(r"^Shelfmark", t):
            shelfmark = re.sub(r"^Shelfmark\s*:?\s*", "", t).strip()

    archive_url: str | None = None
    for a in soup.find_all("a", href=True):
        h = a["href"].strip()
        if "computus.huma-num.fr/mss/" in h:
            continue
        if any(hint in h for hint in ARCHIVE_LINK_HINTS):
            archive_url = h
            break
    if not archive_url:
        archive_url = _field(text, r"Archive Ms\. Page:\s*(\S+)")

    display = _field(text, r"Explore Manuscripts:\s*(.+)")
    if not display:
        for h2 in soup.find_all("h2"):
            t = h2.get_text(strip=True)
            if "Explore" not in t and len(t) > 8:
                display = t
                break
    display = display or slug

    texts: list[str] = []
    for li in soup.find_all("li"):
        t = li.get_text(" ", strip=True)
        if re.search(r"\(f\.\d", t) and not re.match(r"^f\.\d", t):
            texts.append(t)

    m = re.search(r"Texts \((\d+)\)", text)
    text_count = int(m.group(1)) if m else len(texts)

    return {
        "id": slug,
        "source": "citca",
        "citca_url": url,
        "display": display,
        "archive": archive,
        "shelfmark": shelfmark,
        "origin": _field(text, r"CitCA place:\s*([^|\n]+)"),
        "date_citca": _field(text, r"CitCA date:\s*([^|\n]+)"),
        "date_computistical": _field(text, r"Computistical Date:\s*([^|\n]+)"),
        "archive_ms_page": archive_url,
        "text_count_indexed": text_count,
        "texts": texts,
        "strigil_acquire": bool(archive_url),
        "doc_type": "computus_medieval_latin",
        "bib_keys": ["ComputusCarolingianAge"],
    }


def crawl_citca(*, workers: int = 4, delay: float = 0.15) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        slugs = list_slugs(client)
        print(f"CitCA catalogue: {len(slugs)} manuscripts", file=sys.stderr)

        def fetch_one(slug: str) -> dict[str, Any]:
            time.sleep(delay)
            r = client.get(BASE_MS_URL + slug)
            r.raise_for_status()
            return parse_ms_page(r.text, slug)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(fetch_one, s): s for s in slugs}
            for fut in as_completed(futs):
                items.append(fut.result())
    items.sort(key=lambda x: x["id"])
    return items


def build_manifest(citca: list[dict[str, Any]]) -> dict[str, Any]:
    local = [dict(w) for w in LOCAL_WITNESSES]
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalogues": {
            "citca": {
                "title": "Computus in the Carolingian Age",
                "list_url": LIST_URL,
                "count": len(citca),
            },
            "local": {
                "title": "transcription-shell local witnesses",
                "count": len(local),
            },
        },
        "manuscripts": citca + local,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_DIR / "manifest.json",
        help="Output manifest path",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.15)
    args = parser.parse_args()

    citca = crawl_citca(workers=args.workers, delay=args.delay)
    manifest = build_manifest(citca)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with_urls = sum(1 for m in citca if m.get("archive_ms_page"))
    with_texts = sum(1 for m in citca if m.get("texts"))
    print(
        f"Wrote {args.out} — CitCA: {len(citca)} MSS, "
        f"{with_urls} with archive_ms_page, {with_texts} with parsed texts; "
        f"+ {len(LOCAL_WITNESSES)} local witnesses",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
