"""Drive glyphmachina.com: upload pre-cropped image, Identify Lines, Download Lines File.

Selectors target the public UI as of 2026; the site may change — see docs/glyph-machina-automation.md.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout

from transcriber_shell.config import Settings
from transcriber_shell.glyph_machina.browser import playwright_browser


class GlyphMachinaError(RuntimeError):
    pass


def _checksum_image(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def fetch_lines_xml(
    image_path: Path,
    job_id: str,
    settings: Settings | None = None,
) -> Path:
    """Upload ``image_path``, run Identify Lines, save downloaded lines XML under artifacts.

    Returns path to saved XML. Raises GlyphMachinaError on UI or timeout failures.
    """
    s = settings or Settings()
    image_path = image_path.expanduser().resolve()
    if not image_path.is_file():
        raise GlyphMachinaError(f"image not found: {image_path}")

    out_dir = (s.artifacts_dir / job_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = out_dir / "source_image.sha256"
    meta.write_text(f"{_checksum_image(image_path)}  {image_path.name}\n", encoding="utf-8")

    timeout = s.gm_timeout_ms

    with playwright_browser(s) as (_p, browser):
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(timeout)
        try:
            page.goto(s.gm_base_url, wait_until="domcontentloaded")

            file_input = page.locator('input[type="file"]').first
            file_input.wait_for(state="attached", timeout=timeout)
            file_input.set_input_files(str(image_path))
            page.wait_for_timeout(800)

            # Accept crop: pre-cropped images should fill the frame; button label on site is "Crop Image"
            crop = page.get_by_role("button", name="Crop Image")
            if crop.count() > 0:
                crop.first.click()

            identify = page.get_by_role("button", name="Identify Lines")
            identify.wait_for(state="visible", timeout=timeout)
            identify.click()

            # Wait until line step offers download (text may be link or button)
            download_trigger = page.get_by_text("Download Lines File", exact=True)
            download_trigger.wait_for(state="visible", timeout=timeout)

            with page.expect_download(timeout=timeout) as dl_info:
                download_trigger.click()
            download = dl_info.value
            suggested = download.suggested_filename or f"{job_id}-lines.xml"
            out_path = out_dir / suggested
            download.save_as(str(out_path))

            if not out_path.is_file() or out_path.stat().st_size == 0:
                raise GlyphMachinaError("downloaded lines file is missing or empty")

            return out_path

        except PlaywrightTimeout as e:
            raise GlyphMachinaError(f"Glyph Machina UI timed out: {e}") from e
        finally:
            context.close()
