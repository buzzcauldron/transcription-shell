#!/usr/bin/env python3
"""Shared strigil CLI flag selection for manuscript image acquisition.

Maps host/URL shapes onto strigil adapters and polite scrape settings.
Never embeds free-text shelfmarks as CLI args.
"""
from __future__ import annotations

from urllib.parse import urlparse


# Hosts that typically need Playwright for page → asset discovery
_JS_HOST_FRAGMENTS = (
    "bl.uk",
    "britishlibrary",
    "wellcomecollection.org",
    "themorgan.org",
    "morgan.org",
    "diglib.hab.de",
    "internetculturale.it",
    "digital.staatsbibliothek-berlin.de",
    "viewer.staatsbibliothek-berlin.de",
    "digitalcollections.nypl.org",
    "iiif.nypl.org",
    "cudl.lib.cam.ac.uk",
    "parker.stanford.edu",
    "hollis.harvard.edu",
    "nrs.harvard.edu",
    # JS viewers that previously failed positional TSV / thin scrapes
    "warburg-archive.sas.ac.uk",
    "bibliotheque-numerique.dijon.fr",
    "patrimoine.bm-dijon.fr",
    "bvmm.irht.cnrs.fr",
    "portail.biblissima.fr",
)

# Prefer explicit --source adapter when auto-detection is flaky
_SOURCE_BY_HOST = {
    "wellcomecollection.org": "wellcome",
    "iiif.wellcomecollection.org": "wellcome",
    "archive.org": "archive_org",
    "iiif.archive.org": "archive_org",
    "babel.hathitrust.org": "hathitrust",
    "hdl.handle.net": "hathitrust",  # sometimes HT handles
}


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def looks_like_iiif_manifest(url: str) -> bool:
    u = url.lower().split("?")[0]
    if u.rstrip("/").endswith("/manifest") or u.rstrip("/").endswith("/manifest.json"):
        return True
    if "/iiif/" in u and "manifest" in u:
        return True
    if "iiif.archive.org" in u and "/manifest" in u:
        return True
    return False


def strigil_flags(
    url: str,
    *,
    page_estimate: int | None = None,
    polite: bool = True,
) -> list[str]:
    """Return CLI tokens after argv baseline (do not include --url / --out-dir)."""
    host = host_of(url)
    low = url.lower()
    flags: list[str] = []

    # Adapter selection — only real strigil ADAPTER_BY_SOURCE keys.
    # Generic IIIF is auto-detected from the URL; do not force --source iiif.
    source: str | None = None
    for hfrag, adapter in _SOURCE_BY_HOST.items():
        if hfrag in host:
            source = adapter
            break
    # HathTrust explicit pages
    if source is None and ("hathitrust.org" in host or "hdl.handle.net" in host):
        source = "hathitrust"
    if source is None and "wellcomecollection" in host:
        source = "wellcome"
    if source is None and ("archive.org" in host or "iiif.archive.org" in host):
        source = "archive_org"

    if source:
        flags.extend(["--source", source])

    # JS for bot-protected / SPA viewers
    if any(frag in host or frag in low for frag in _JS_HOST_FRAGMENTS):
        if "--js" not in flags:
            flags.append("--js")

    # Politeness / resilience for flaky repositories
    if polite:
        if "gallica.bnf.fr" in host:
            flags.extend(
                [
                    "--sequential",
                    "--aggressiveness",
                    "conservative",
                    "--delay",
                    "2.0",
                    "--max-iterations",
                    "4",
                ]
            )
        elif any(
            h in host
            for h in (
                "digi.vatlib.it",
                "archive.org",
                "iiif.archive.org",
                "bl.uk",
                "britishlibrary",
            )
        ):
            flags.extend(["--aggressiveness", "conservative", "--workers", "8"])
        else:
            flags.extend(["--aggressiveness", "balanced"])

    if page_estimate and page_estimate > 0:
        flags.extend(["--expected-images", str(int(page_estimate))])

    # Always retry once on flaky CDN failures
    if "--retry-failed" not in flags and "--no-retry-failed" not in flags:
        flags.append("--retry-failed")

    return flags


def with_parallel_workers(flags: list[str], url: str, workers: int) -> list[str]:
    """Force parallel asset downloads except on Gallica (BnF rate-limits)."""
    if workers <= 1:
        return list(flags)
    host = host_of(url)
    if "gallica.bnf.fr" in host:
        return list(flags)
    out: list[str] = []
    skip_next = False
    for tok in flags:
        if skip_next:
            skip_next = False
            continue
        if tok == "--sequential":
            continue
        if tok == "--workers":
            skip_next = True
            continue
        out.append(tok)
    out.extend(["--workers", str(max(2, int(workers)))])
    return out


def strigil_cmd(
    python: str,
    url: str,
    out_dir: str,
    *,
    page_estimate: int | None = None,
    workers_default: int = 8,
    extra_flags: list[str] | None = None,
) -> list[str]:
    """Full subprocess argv for a manuscript image scrape."""
    flags = list(extra_flags) if extra_flags is not None else strigil_flags(
        url, page_estimate=page_estimate
    )
    # If host-specific flags already set workers, don't force default
    has_workers = False
    for i, tok in enumerate(flags):
        if tok == "--workers" or tok == "--sequential":
            has_workers = True
            break
    cmd = [
        python,
        "-m",
        "strigil.cli",
        "--url",
        url,
        "--out-dir",
        out_dir,
        "--types",
        "images",
        "--manuscript",
        "--min-image-size",
        "200k",
        "--no-progress",
    ]
    if not has_workers:
        cmd.extend(["--workers", str(workers_default)])
    cmd.extend(flags)
    return cmd
