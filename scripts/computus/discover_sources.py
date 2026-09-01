#!/usr/bin/env python3
"""Validate and discover web sources for the computus union registry.

Stage A (default): validate existing candidate URLs (HEAD/GET, IIIF probe).
Stage B (--discover): for records still without confirmed URLs, query public
APIs (Archive.org, simple institutional URL heuristics). Every candidate is
stored with evidence; confirmation requires host/page success.

Respects robots.txt per host. Does not use --no-robots.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.robotparser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REG = (
    REPO_ROOT / "references/computus-library/web_harvest/union_registry.jsonl"
)
USER_AGENT = "transcription-shell-computus-harvest/1.0 (research; +https://github.com/)"
HOST_MIN_INTERVAL = {
    "gallica.bnf.fr": 2.0,
    "iiif.archive.org": 1.0,
    "archive.org": 1.5,
    "digi.vatlib.it": 1.0,
    "api.digitale-sammlungen.de": 0.8,
    "www.e-codices.unifr.ch": 0.8,
    "iiif.bodleian.ox.ac.uk": 0.8,
}
DEFAULT_INTERVAL = 0.5

_last_hit: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


def throttle(host: str) -> None:
    wait = HOST_MIN_INTERVAL.get(host, DEFAULT_INTERVAL)
    last = _last_hit.get(host, 0.0)
    gap = time.time() - last
    if gap < wait:
        time.sleep(wait - gap)
    _last_hit[host] = time.time()


def robots_allowed(url: str, client: httpx.Client) -> bool | None:
    host = host_of(url)
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{urllib.parse.urlparse(url).scheme}://{host}/robots.txt"
        try:
            throttle(host)
            r = client.get(robots_url, timeout=20.0)
            if r.status_code >= 400:
                _robots[host] = None
            else:
                rp.parse(r.text.splitlines())
                _robots[host] = rp
        except Exception:
            _robots[host] = None
    rp = _robots[host]
    if rp is None:
        return None  # unknown / failed fetch → allow with caution
    try:
        return bool(rp.can_fetch(USER_AGENT, url))
    except Exception:
        return None


def count_canvases(manifest: dict[str, Any]) -> int | None:
    # IIIF Presentation v2
    seq = manifest.get("sequences") or []
    if seq:
        canvases = seq[0].get("canvases") or []
        return len(canvases) if canvases else None
    # IIIF Presentation v3
    items = manifest.get("items") or []
    if items:
        return len(items)
    return None


def extract_rights(manifest: dict[str, Any]) -> str | None:
    for key in ("license", "rights", "attribution", "requiredStatement"):
        if key in manifest and manifest[key]:
            val = manifest[key]
            if isinstance(val, str):
                return val[:500]
            if isinstance(val, dict):
                # v3 requiredStatement
                label = val.get("label") or val.get("value")
                return json.dumps(label, ensure_ascii=False)[:500]
            if isinstance(val, list) and val:
                return str(val[0])[:500]
    meta = manifest.get("metadata") or []
    for item in meta:
        label = str(item.get("label", "")).lower()
        if "right" in label or "license" in label or "attribution" in label:
            return str(item.get("value"))[:500]
    return None


@dataclass
class ProbeResult:
    ok: bool
    status_code: int | None
    final_url: str | None
    content_type: str | None
    iiif: bool
    page_count: int | None
    rights: str | None
    robots: bool | None
    error: str | None
    title: str | None = None


def probe_url(url: str, client: httpx.Client) -> ProbeResult:
    host = host_of(url)
    allowed = robots_allowed(url, client)
    if allowed is False:
        return ProbeResult(
            False, None, url, None, False, None, None, False, "robots_disallow", None
        )
    try:
        throttle(host)
        # Prefer GET for IIIF (HEAD often broken); stream small body
        with client.stream("GET", url, timeout=45.0, follow_redirects=True) as r:
            status = r.status_code
            final = str(r.url)
            ctype = r.headers.get("content-type", "")
            if status >= 400:
                return ProbeResult(
                    False, status, final, ctype, False, None, None, allowed,
                    f"http_{status}", None
                )
            # Read up to 2MB for manifests
            chunks = []
            size = 0
            for chunk in r.iter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size > 2_000_000:
                    break
            body = b"".join(chunks)
        text = body.decode("utf-8", errors="replace")
        iiif = False
        pages = None
        rights = None
        title = None
        low = ctype.lower()
        if "json" in low or text.lstrip().startswith("{") or text.lstrip().startswith("["):
            try:
                data = json.loads(text)
                if isinstance(data, dict) and (
                    data.get("@type")
                    or data.get("type")
                    or "sequences" in data
                    or data.get("items")
                    or data.get("@context")
                ):
                    iiif = True
                    pages = count_canvases(data)
                    rights = extract_rights(data)
                    label = data.get("label")
                    if isinstance(label, str):
                        title = label[:300]
                    elif isinstance(label, dict):
                        # v3 label maps language -> [strings]
                        for vs in label.values():
                            if isinstance(vs, list) and vs:
                                title = str(vs[0])[:300]
                                break
            except json.JSONDecodeError:
                pass
        return ProbeResult(
            True, status, final, ctype, iiif, pages, rights, allowed, None, title
        )
    except Exception as exc:
        return ProbeResult(
            False, None, url, None, False, None, None, allowed, type(exc).__name__ + ": " + str(exc)[:200], None
        )


def shelf_tokens(shelf: str) -> list[str]:
    s = re.sub(r"[^a-zA-Z0-9]+", " ", shelf)
    toks = [t for t in s.split() if len(t) > 1]
    return toks


def archive_org_search(shelf: str, client: httpx.Client) -> list[dict[str, Any]]:
    """Search Internet Archive advancedsearch for shelfmark-ish item."""
    toks = shelf_tokens(shelf)
    if len(toks) < 2:
        return []
    # Prefer distinctive tail tokens (lat, clm, numbers)
    q_core = " ".join(toks[:6])
    query = f'mediatype:(texts) AND ({q_core})'
    params = {
        "q": query,
        "fl[]": ["identifier", "title", "description", "licenseurl", "publicdate"],
        "rows": 5,
        "page": 1,
        "output": "json",
        "sort[]": "downloads desc",
    }
    url = "https://archive.org/advancedsearch.php"
    try:
        throttle("archive.org")
        r = client.get(url, params=params, timeout=40.0)
        r.raise_for_status()
        docs = (r.json().get("response") or {}).get("docs") or []
    except Exception:
        return []
    hits = []
    shelf_l = shelf.lower()
    for doc in docs:
        title = str(doc.get("title") or "")
        ident = doc.get("identifier")
        if not ident:
            continue
        conf = "low"
        tlow = title.lower()
        # crude agreement: at least 2 distinctive tokens in title
        matches = sum(1 for t in toks if t.lower() in tlow)
        if matches >= 3:
            conf = "medium"
        # strong: key shelf number present
        if any(t.isdigit() and len(t) >= 2 and t in tlow for t in toks) and matches >= 2:
            conf = "high"
        item_url = f"https://archive.org/details/{ident}"
        meta_url = f"https://archive.org/metadata/{ident}"
        hits.append(
            {
                "url": item_url,
                "kind": "archive_org",
                "host": "archive.org",
                "provenance": "archive.org:advancedsearch",
                "status": "candidate",
                "confidence": conf,
                "evidence": {
                    "title": title[:300],
                    "identifier": ident,
                    "token_matches": matches,
                    "query": q_core,
                    "shelf": shelf,
                },
                "meta_url": meta_url,
            }
        )
    return hits


def catalog_linked(cand: dict[str, Any]) -> bool:
    prov = str(cand.get("provenance") or "").lower()
    return any(
        p in prov
        for p in (
            "computus.lat",
            "citca:",
            "cohort:",
            "manifest:",
            "catalog",
        )
    )


def confirm_threshold(cand: dict[str, Any], probe: ProbeResult) -> str:
    """Mark confirmed only with IIIF/probe success + high confidence or catalogue link."""
    if not probe.ok:
        return "failed"
    if probe.robots is False:
        return "failed"
    # Catalogue-linked IIIF or working digitization page with explicit source
    if catalog_linked(cand) and cand.get("confidence") in ("high", "medium"):
        if probe.iiif or cand.get("kind") in ("iiif", "digitization_page"):
            return "confirmed"
    if cand.get("confidence") == "high" and (
        probe.iiif or cand["kind"] in ("iiif", "digitization_page")
    ):
        return "confirmed"
    if probe.iiif and cand.get("confidence") in ("high", "medium"):
        return "confirmed"
    if cand["kind"] == "archive_org" and cand.get("confidence") == "high" and probe.ok:
        return "confirmed"
    if probe.ok:
        return "ambiguous"
    return "failed"


# --- repository-specific discovery helpers ---------------------------------

def digivatlib_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """Heuristic DigiVatLib IIIF URLs from Vatican shelfmarks."""
    inst = (institution or shelf or "").lower()
    if "vatican" not in inst and "vaticana" not in inst and "bav" not in inst:
        if not re.search(r"\b(reg|pal|vat|barb|ott|urb|ross)\.?\s*lat\.?", shelf, re.I):
            return []
    # Normalize e.g. "Reg. lat. 123", "Pal. lat. 1407", "Vat. lat. 645"
    m = re.search(
        r"\b(reg|pal|vat|barb|ott|urb|ross)\.?\s*lat\.?\s*(\d+[a-z]?)\b",
        shelf,
        re.I,
    )
    if not m:
        return []
    fund = m.group(1).lower()
    num = m.group(2)
    fund_map = {
        "reg": "Reg.lat",
        "pal": "Pal.lat",
        "vat": "Vat.lat",
        "barb": "Barb.lat",
        "ott": "Ott.lat",
        "urb": "Urb.lat",
        "ross": "Ross",
    }
    code = fund_map.get(fund)
    if not code:
        return []
    mss = f"{code}.{num}"
    iiif = f"https://digi.vatlib.it/iiif/{mss}/manifest.json"
    page = f"https://digi.vatlib.it/view/{mss}"
    return [
        {
            "url": iiif,
            "kind": "iiif",
            "host": "digi.vatlib.it",
            "provenance": "adapter:digivatlib_shelfmark",
            "status": "candidate",
            "confidence": "medium",
            "evidence": {"mss_code": mss, "shelf": shelf},
        },
        {
            "url": page,
            "kind": "digitization_page",
            "host": "digi.vatlib.it",
            "provenance": "adapter:digivatlib_view",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"mss_code": mss, "shelf": shelf},
        },
    ]


def bsb_mdz_candidates(shelf: str, institution: str, client: httpx.Client) -> list[dict[str, Any]]:
    """BSB / MDZ open API search for Clm shelfmarks."""
    if not re.search(r"\bClm\b|\bCod\.?\s*lat\.?\s*mon", shelf, re.I) and "münchen" not in (
        institution or ""
    ).lower() and "munich" not in (institution or "").lower() and "bsb" not in (
        institution or ""
    ).lower():
        return []
    m = re.search(r"\bClm\s*(\d+[a-z]?)\b", shelf, re.I)
    if not m:
        return []
    q = f"Clm {m.group(1)}"
    api = "https://api.digitale-sammlungen.de/iiif/presentation/v2/collection/top"
    # MDZ search endpoint
    search = "https://api.digitale-sammlungen.de/search"
    try:
        throttle("api.digitale-sammlungen.de")
        r = client.get(
            search,
            params={"query": q, "limit": 5, "offset": 0},
            timeout=30.0,
        )
        if r.status_code >= 400:
            return []
        data = r.json()
    except Exception:
        return []
    hits: list[dict[str, Any]] = []
    docs = data.get("docs") or data.get("hits") or data.get("items") or []
    if isinstance(data, dict) and "response" in data:
        docs = data["response"].get("docs") or docs
    for doc in docs[:5]:
        if not isinstance(doc, dict):
            continue
        title = str(doc.get("title") or doc.get("label") or "")
        # Common MDZ fields
        obj_id = doc.get("id") or doc.get("mdzid") or doc.get("objectId")
        manifest = doc.get("manifest") or doc.get("iiifManifest")
        if not manifest and obj_id:
            manifest = (
                f"https://api.digitale-sammlungen.de/iiif/presentation/v2/"
                f"{obj_id}/manifest"
            )
        if not manifest:
            continue
        conf = "medium" if m.group(1) in title else "low"
        if f"clm {m.group(1)}".lower() in title.lower():
            conf = "high"
        hits.append(
            {
                "url": manifest,
                "kind": "iiif",
                "host": "api.digitale-sammlungen.de",
                "provenance": "adapter:bsb_mdz_search",
                "status": "candidate",
                "confidence": conf,
                "evidence": {"title": title[:300], "query": q, "id": obj_id},
            }
        )
    return hits


def gallica_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """Build Gallica HTML search URLs for BnF Latin shelfmarks (not auto-confirmed)."""
    inst = (institution or "").lower()
    if "bnf" not in inst and "gallica" not in inst and "nationale de france" not in inst:
        if not re.search(r"\blat\.?\s*\d+", shelf, re.I):
            return []
    m = re.search(r"\blat\.?\s*(\d+[a-z]?)\b", shelf, re.I)
    if not m:
        return []
    q = urllib.parse.quote(f"Latin {m.group(1)}")
    url = f"https://gallica.bnf.fr/services/engine/search/sru?operation=searchRetrieve&version=1.2&query=%28gallica%20all%20%22Latin%20{m.group(1)}%22%29&maximumRecords=5"
    return [
        {
            "url": url,
            "kind": "catalogue_api",
            "host": "gallica.bnf.fr",
            "provenance": "adapter:gallica_sru",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"shelf": shelf, "lat": m.group(1)},
        }
    ]


def e_codices_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """e-codices page heuristics for Swiss libraries."""
    inst = (institution or shelf or "").lower()
    swiss_hints = (
        "e-codices",
        "st. gall",
        "sankt gallen",
        "einsiedeln",
        "basel",
        "bern",
        "zurich",
        "fribourg",
        "cologny",
        "schaffhausen",
    )
    if not any(h in inst for h in swiss_hints):
        return []
    # Common pattern: https://www.e-codices.unifr.ch/en/list/one/xxx/yyy — too free-form
    # Provide catalogue search only
    q = urllib.parse.quote_plus((shelf or "")[:80])
    return [
        {
            "url": f"https://www.e-codices.unifr.ch/en/search/all?query={q}",
            "kind": "catalogue_search",
            "host": "www.e-codices.unifr.ch",
            "provenance": "adapter:ecodices_search",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"query": shelf},
        }
    ]


def europeana_candidates(shelf: str, client: httpx.Client) -> list[dict[str, Any]]:
    """Europeana Search API (no key required for tiny quota; skip on failure)."""
    toks = shelf_tokens(shelf)
    if len(toks) < 2:
        return []
    q = " ".join(toks[:5])
    url = "https://api.europeana.eu/record/v2/search.json"
    try:
        throttle("api.europeana.eu")
        r = client.get(
            url,
            params={"query": q, "rows": 3, "profile": "minimal", "wskey": "api2demo"},
            timeout=30.0,
        )
        if r.status_code >= 400:
            return []
        items = (r.json().get("items") or [])[:3]
    except Exception:
        return []
    hits = []
    for it in items:
        link = it.get("guid") or it.get("link")
        title = " ".join(it.get("title") or []) if isinstance(it.get("title"), list) else str(it.get("title") or "")
        if not link:
            continue
        matches = sum(1 for t in toks if t.lower() in title.lower())
        conf = "medium" if matches >= 3 else "low"
        hits.append(
            {
                "url": link,
                "kind": "catalogue_page",
                "host": host_of(link) or "europeana.eu",
                "provenance": "adapter:europeana_search",
                "status": "candidate",
                "confidence": conf,
                "evidence": {"title": title[:300], "query": q, "matches": matches},
            }
        )
    return hits


def bodleian_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """Heuristics for Bodleian / Oxford IIIF when shelf is recognizable."""
    inst = (institution or shelf or "").lower()
    if not any(
        x in inst
        for x in ("bodleian", "oxford", "st john", "magdalen", "all souls", "balliol")
    ):
        if not re.search(r"\b(MS\.?\s*Bodl|MS\.?\s*Auct|MS\.?\s*Rawl|MS\.?\s*Digby)\b", shelf, re.I):
            return []
    # Prefer existing catalogue URL shapes: digital.bodleian objects are free-form;
    # emit a targeted catalogue search (not auto-confirmed).
    q = urllib.parse.quote_plus((shelf or "")[:100])
    return [
        {
            "url": f"https://digital.bodleian.ox.ac.uk/search/?q={q}",
            "kind": "catalogue_search",
            "host": "digital.bodleian.ox.ac.uk",
            "provenance": "adapter:bodleian_search",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"query": shelf},
        }
    ]


def heidelberg_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """Heidelberg UB digi search for Cod. Pal. germ. / lat."""
    inst = (institution or shelf or "").lower()
    if "heidelberg" not in inst and "pal. germ" not in inst and "pal. lat" not in (
        shelf or ""
    ).lower():
        if not re.search(r"\bCod\.?\s*Pal\.?", shelf, re.I):
            return []
    q = urllib.parse.quote_plus((shelf or "")[:80])
    return [
        {
            "url": f"https://digi.ub.uni-heidelberg.de/diglit/search?q={q}",
            "kind": "catalogue_search",
            "host": "digi.ub.uni-heidelberg.de",
            "provenance": "adapter:heidelberg_search",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"query": shelf},
        }
    ]


def cologne_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """Cologne Dom library digitals for Cod. / Dombibliothek shelfmarks."""
    inst = (institution or shelf or "").lower()
    if "köln" not in inst and "koeln" not in inst and "cologne" not in inst:
        if "dombibliothek" not in inst:
            return []
    q = urllib.parse.quote_plus((shelf or "")[:80])
    return [
        {
            "url": f"https://digital.dombibliothek-koeln.de/hs/nav/classification/search?q={q}",
            "kind": "catalogue_search",
            "host": "digital.dombibliothek-koeln.de",
            "provenance": "adapter:cologne_search",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"query": shelf},
        }
    ]


def wellcome_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """Wellcome Collection works search for MS numbers."""
    inst = (institution or shelf or "").lower()
    if "wellcome" not in inst:
        return []
    m = re.search(r"\bMS\.?\s*(\d+)\b", shelf, re.I) or re.search(r"\b(\d{1,5})\b", shelf)
    q = urllib.parse.quote_plus((shelf or "")[:80])
    url = f"https://wellcomecollection.org/search/works?query={q}"
    hits = [
        {
            "url": url,
            "kind": "catalogue_search",
            "host": "wellcomecollection.org",
            "provenance": "adapter:wellcome_search",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"query": shelf},
        }
    ]
    if m:
        # Common IIIF path pattern when MS number matches a work id (weak).
        hits.append(
            {
                "url": f"https://wellcomecollection.org/works?query=MS%20{m.group(1)}",
                "kind": "catalogue_search",
                "host": "wellcomecollection.org",
                "provenance": "adapter:wellcome_ms_query",
                "status": "candidate",
                "confidence": "low",
                "evidence": {"ms": m.group(1)},
            }
        )
    return hits


def bvmm_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """IRHT BVMM catalogue search."""
    inst = (institution or shelf or "").lower()
    if "bvmm" not in inst and "irht" not in inst and "cnrs" not in inst:
        # French municipal / diocesan collections often only present via BVMM
        french_hints = ("chartres", "dijon", "reims", "troyes", "angers", "amiens")
        if not any(h in inst for h in french_hints):
            return []
    q = urllib.parse.quote_plus((shelf or "")[:80])
    return [
        {
            "url": f"https://bvmm.irht.cnrs.fr/resultRecherche/resultRecherche.php?COMPOSITION_libelle={q}",
            "kind": "catalogue_search",
            "host": "bvmm.irht.cnrs.fr",
            "provenance": "adapter:bvmm_search",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"query": shelf},
        }
    ]


def parker_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """Parker Library / Stanford Digital Manuscripts search."""
    inst = (institution or shelf or "").lower()
    if "parker" not in inst and "corpus christi" not in inst and "stanford" not in inst:
        if not re.search(r"\bCCCC\b|Corpus Christi", shelf, re.I):
            return []
    m = re.search(r"\b(\d{1,3})\b", shelf)
    hits = []
    if m:
        n = m.group(1)
        # Common Stanford IIIF collection id pattern for Parker (confirm via probe)
        hits.append(
            {
                "url": f"https://dms-data.stanford.edu/data/manifests/Parker/cccc{n}/manifest.json",
                "kind": "iiif",
                "host": "dms-data.stanford.edu",
                "provenance": "adapter:parker_manifest_guess",
                "status": "candidate",
                "confidence": "low",
                "evidence": {"cccc": n, "shelf": shelf},
            }
        )
    q = urllib.parse.quote_plus((shelf or "")[:80])
    hits.append(
        {
            "url": f"https://parker.stanford.edu/parker/catalog?f%5Bshelfmark_s%5D%5B%5D={q}",
            "kind": "catalogue_search",
            "host": "parker.stanford.edu",
            "provenance": "adapter:parker_search",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"query": shelf},
        }
    )
    return hits


def berlin_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """SBB Berlin digitised manuscripts search."""
    inst = (institution or shelf or "").lower()
    if "berlin" not in inst and "staatsbibliothek" not in inst and "sbb" not in inst:
        if not re.search(r"\bMs\.\s*lat\.|\bPhill\.|\bDiez\b", shelf, re.I):
            return []
    q = urllib.parse.quote_plus((shelf or "")[:80])
    return [
        {
            "url": f"https://digital.staatsbibliothek-berlin.de/suche?queryString={q}",
            "kind": "catalogue_search",
            "host": "digital.staatsbibliothek-berlin.de",
            "provenance": "adapter:sbb_berlin_search",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"query": shelf},
        }
    ]


def harvard_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """Harvard Hollis / IIIF — often robots-blocked; keep metadata candidates only."""
    inst = (institution or shelf or "").lower()
    if "harvard" not in inst and "houghton" not in inst:
        return []
    q = urllib.parse.quote_plus((shelf or "")[:80])
    return [
        {
            "url": f"https://hollis.harvard.edu/primo-explore/search?query=any,contains,{q}&vid=HVD2",
            "kind": "catalogue_search",
            "host": "hollis.harvard.edu",
            "provenance": "adapter:harvard_hollis",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"query": shelf, "note": "robots often block image pull"},
            "robots_hint": "metadata_only",
        }
    ]


def bl_candidates(shelf: str, institution: str) -> list[dict[str, Any]]:
    """British Library catalogue / digitised manuscripts search."""
    inst = (institution or shelf or "").lower()
    if "british library" not in inst and "bl." not in inst and not re.search(
        r"\b(Harley|Cotton|Royal|Add\.?|Additional)\b", shelf, re.I
    ):
        return []
    q = urllib.parse.quote_plus((shelf or "")[:80])
    return [
        {
            "url": f"https://searcharchives.bl.uk/primo_library/libweb/action/search.do?fn=search&vl(freeText0)={q}",
            "kind": "catalogue_search",
            "host": "searcharchives.bl.uk",
            "provenance": "adapter:bl_archives_search",
            "status": "candidate",
            "confidence": "low",
            "evidence": {"query": shelf},
        }
    ]


def discover_for_record(rec: dict[str, Any], client: httpx.Client) -> list[dict[str, Any]]:
    """Run repository adapters for unresolved records; return new candidates."""
    shelf = rec.get("display") or rec.get("shelfmark") or ""
    institution = rec.get("institution") or ""
    hits: list[dict[str, Any]] = []
    hits.extend(digivatlib_candidates(shelf, institution))
    hits.extend(bsb_mdz_candidates(shelf, institution, client))
    hits.extend(gallica_candidates(shelf, institution))
    hits.extend(e_codices_candidates(shelf, institution))
    hits.extend(bodleian_candidates(shelf, institution))
    hits.extend(heidelberg_candidates(shelf, institution))
    hits.extend(cologne_candidates(shelf, institution))
    hits.extend(wellcome_candidates(shelf, institution))
    hits.extend(bvmm_candidates(shelf, institution))
    hits.extend(parker_candidates(shelf, institution))
    hits.extend(berlin_candidates(shelf, institution))
    hits.extend(harvard_candidates(shelf, institution))
    hits.extend(bl_candidates(shelf, institution))
    hits.extend(europeana_candidates(shelf, client))
    hits.extend(archive_org_search(shelf, client))
    return hits


def process_record(
    rec: dict[str, Any],
    client: httpx.Client,
    *,
    discover: bool,
) -> dict[str, Any]:
    acq = rec.setdefault("acquisition", {})
    if acq.get("status") in ("local", "downloaded", "confirmed"):
        return rec

    # Validate existing candidates first
    for cand in list(rec.get("candidate_urls") or []):
        url = cand["url"]
        probe = probe_url(url, client)
        cand["status"] = "ok" if probe.ok else "failed"
        cand["http_status"] = probe.status_code
        cand["final_url"] = probe.final_url
        cand["content_type"] = probe.content_type
        cand["iiif"] = probe.iiif
        cand["page_count"] = probe.page_count
        cand["rights"] = probe.rights
        cand["robots_allowed"] = probe.robots
        cand["error"] = probe.error
        cand["probed_at"] = now()
        if probe.title:
            cand["remote_title"] = probe.title
        decision = confirm_threshold(cand, probe)
        cand["decision"] = decision
        if decision == "confirmed" and acq.get("status") not in ("confirmed", "downloaded"):
            acq["status"] = "confirmed"
            acq["confirmed_url"] = probe.final_url or url
            acq["access"] = "public"
            acq["rights"] = probe.rights
            acq["robots_allowed"] = probe.robots
            acq["page_estimate"] = probe.page_count
            acq["last_error"] = None
        elif decision == "failed" and not acq.get("confirmed_url"):
            acq["last_error"] = probe.error
            if probe.robots is False:
                acq["status"] = "access_blocked"
                acq["access"] = "robots_blocked"
                acq["robots_allowed"] = False
            elif acq.get("status") not in ("access_blocked", "confirmed"):
                acq["status"] = "url_failed"

    # Discovery for unresolved
    if discover and acq.get("status") not in ("confirmed", "downloaded", "local", "access_blocked"):
        shelf = rec.get("display") or rec.get("shelfmark") or ""
        if shelf:
            hits = discover_for_record(rec, client)
            existing = {c["url"] for c in rec.get("candidate_urls") or []}
            for hit in hits:
                if hit["url"] in existing:
                    continue
                # Probe IIIF / pages; leave catalogue_search / API lists unprobed deep
                kind = hit.get("kind") or ""
                if kind in ("catalogue_search", "catalogue_api"):
                    hit["decision"] = "ambiguous"
                    hit["status"] = "candidate"
                    hit["probed_at"] = now()
                    rec.setdefault("candidate_urls", []).append(hit)
                    continue
                probe = probe_url(hit["url"], client)
                hit["http_status"] = probe.status_code
                hit["final_url"] = probe.final_url
                hit["error"] = probe.error
                hit["robots_allowed"] = probe.robots
                hit["iiif"] = probe.iiif
                hit["page_count"] = probe.page_count
                hit["rights"] = probe.rights
                hit["probed_at"] = now()
                if probe.title:
                    hit["remote_title"] = probe.title
                decision = confirm_threshold(hit, probe)
                hit["decision"] = decision
                hit["status"] = "ok" if probe.ok else "failed"
                if decision == "confirmed" and acq.get("status") not in (
                    "confirmed",
                    "downloaded",
                ):
                    acq["status"] = "confirmed"
                    acq["confirmed_url"] = probe.final_url or hit["url"]
                    acq["access"] = "public_" + kind
                    acq["robots_allowed"] = probe.robots
                    acq["page_estimate"] = probe.page_count
                    acq["rights"] = probe.rights
                rec.setdefault("candidate_urls", []).append(hit)
                if hit["kind"] == "archive_org" and hit["url"] not in rec.get(
                    "archive_org_urls", []
                ):
                    rec.setdefault("archive_org_urls", []).append(hit["url"])
            if acq.get("status") not in ("confirmed", "downloaded", "access_blocked"):
                if not rec.get("candidate_urls"):
                    acq["status"] = "not_digitized_unknown"
                else:
                    # had candidates but none confirmed
                    if all(
                        c.get("decision") in ("failed", None)
                        for c in rec["candidate_urls"]
                    ):
                        acq["status"] = "url_failed"
                    else:
                        acq["status"] = "needs_review"

    # Final fall-through
    if acq.get("status") in ("pending", "has_url") and not acq.get("confirmed_url"):
        any_ok = any(c.get("status") == "ok" for c in rec.get("candidate_urls") or [])
        if any_ok:
            acq["status"] = "needs_review"
        elif not rec.get("candidate_urls"):
            acq["status"] = "needs_discovery" if not discover else "not_digitized_unknown"
    return rec


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", type=Path, default=DEFAULT_REG)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument(
        "--only-status",
        nargs="*",
        default=None,
        help="Only process records with these acquisition.status values",
    )
    args = ap.parse_args()
    out_path = args.out or args.registry.with_name(
        "union_registry_discovered.jsonl" if args.discover else "union_registry_validated.jsonl"
    )
    rows = load_jsonl(args.registry)
    if args.only_status:
        want = set(args.only_status)
        todo_idx = [i for i, r in enumerate(rows) if r.get("acquisition", {}).get("status") in want]
    else:
        todo_idx = list(range(len(rows)))
    if args.limit > 0:
        todo_idx = todo_idx[: args.limit]

    print(
        f"[discover] records={len(rows)} todo={len(todo_idx)} "
        f"discover={args.discover} workers={args.workers}",
        file=sys.stderr,
    )

    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}

    def work(i: int) -> tuple[int, dict[str, Any]]:
        # Per-thread client: shared httpx.Client is not thread-safe
        with httpx.Client(headers=headers, follow_redirects=True, timeout=45.0) as client:
            return i, process_record(rows[i], client, discover=args.discover)

    if args.workers <= 1:
        for n, i in enumerate(todo_idx, 1):
            _, rec = work(i)
            rows[i] = rec
            if n % 25 == 0 or n == len(todo_idx):
                print(f"[discover] {n}/{len(todo_idx)}", file=sys.stderr)
    else:
        done = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(work, i): i for i in todo_idx}
            for fut in as_completed(futs):
                i, rec = fut.result()
                rows[i] = rec
                done += 1
                if done % 25 == 0 or done == len(todo_idx):
                    print(f"[discover] {done}/{len(todo_idx)}", file=sys.stderr)

    write_jsonl(out_path, rows)

    status = defaultdict(int)
    for r in rows:
        status[r.get("acquisition", {}).get("status", "?")] += 1
    summary = {
        "generated_at": now(),
        "n_records": len(rows),
        "by_status": dict(status),
        "discover": args.discover,
    }
    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
