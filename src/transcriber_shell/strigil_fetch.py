"""Fetch page images from a URL using strigil (IIIF-aware, handles most repositories)."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif"}


def _is_direct_image(url: str) -> bool:
    path = unquote(urlparse(url).path).lower()
    return any(path.endswith(s) for s in _IMAGE_SUFFIXES)


def fetch_images_from_url(
    url: str,
    out_dir: Path,
    *,
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    """Download images from *url* into *out_dir* and return local Paths.

    Handles direct image URLs, HTML pages with embedded images, and IIIF
    manifests.  Uses strigil's schema-detection pipeline so most digital
    library / manuscript repository URLs work without extra configuration.
    """
    from bs4 import BeautifulSoup
    from strigil.fetcher import Fetcher
    from strigil.discovery import collect_image_urls

    out_dir.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher()
    saved: list[Path] = []

    def _log(msg: str) -> None:
        if progress:
            progress(msg)

    try:
        if _is_direct_image(url):
            image_urls = [url]
        else:
            _log("Fetching page…")
            raw, charset = fetcher.fetch_html(url, delay=0)
            html_str = raw.decode(charset, errors="replace")
            soup = BeautifulSoup(html_str, "lxml")

            def _fetch_manifest(u: str) -> bytes:
                return fetcher.fetch_bytes(u)

            image_urls = collect_image_urls(
                soup, url, html_str,
                fetch_manifest=_fetch_manifest,
                limit=limit,
            )
            _log(f"Found {len(image_urls)} image URL(s).")

        if limit:
            image_urls = image_urls[:limit]

        for i, img_url in enumerate(image_urls):
            try:
                _log(f"Downloading {i + 1}/{len(image_urls)}: {img_url[:80]}…")
                data = fetcher.fetch_bytes(img_url)
                parsed_path = unquote(urlparse(img_url).path).lower()
                ext = next((s for s in _IMAGE_SUFFIXES if parsed_path.endswith(s)), ".jpg")
                stem = Path(unquote(urlparse(img_url).path)).stem[:80] or f"img_{i:04d}"
                dest = out_dir / f"{i:04d}_{stem}{ext}"
                dest.write_bytes(data)
                saved.append(dest)
            except Exception as e:
                _log(f"  skip {img_url[:60]}: {e}")
    finally:
        fetcher.close()

    return saved
