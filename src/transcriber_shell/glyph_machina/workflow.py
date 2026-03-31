"""Drive glyphmachina.com: upload pre-cropped image, Identify Lines, Download Lines File.

Selectors target the public UI as of 2026; the site may change — see docs/glyph-machina-automation.md.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from playwright.sync_api import Locator
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from transcriber_shell.config import Settings
from transcriber_shell.glyph_machina.browser import playwright_glyph_context


class GlyphMachinaError(RuntimeError):
    pass


def _checksum_image(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _wait_for_download_control(
    page: Page,
    dloc: Locator,
    *,
    timeout_ms: int,
    hidden_grace_s: float = 6.0,
) -> None:
    """Wait until download is safe to trigger.

    The GM SPA may mount ``#downloadLinesBtn`` before line detection finishes (disabled), or keep it
    enabled but CSS-hidden — waiting only for *visible* or only for *attached* both fail in the wild.
    We poll until the control is enabled, then either visible or ``hidden_grace_s`` after first enabled.
    """
    deadline = time.monotonic() + timeout_ms / 1000.0
    enabled_at: float | None = None
    while time.monotonic() < deadline:
        try:
            en = dloc.is_enabled()
            vis = dloc.is_visible()
        except Exception:
            # Detached nodes or transient DOM errors while the SPA updates.
            page.wait_for_timeout(400)
            continue
        if not en:
            enabled_at = None
            page.wait_for_timeout(400)
            continue
        if enabled_at is None:
            enabled_at = time.monotonic()
        if vis:
            return
        if time.monotonic() - enabled_at >= hidden_grace_s:
            return
        page.wait_for_timeout(350)
    raise GlyphMachinaError(
        "Glyph Machina: download control (#downloadLinesBtn) did not become ready in time "
        f"({timeout_ms} ms). Increase TRANSCRIBER_SHELL_GM_TIMEOUT_MS or "
        "TRANSCRIBER_SHELL_GM_POST_IDENTIFY_WAIT_MS, or use Skip automated lineation with a lines XML file."
    )


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
        raise GlyphMachinaError(
            f"Image path is missing or not a file: {image_path}. "
            "Choose a pre-cropped page image (jpg/png/webp/tiff, etc.)."
        )

    out_dir = (s.artifacts_dir / job_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = out_dir / "source_image.sha256"
    meta.write_text(f"{_checksum_image(image_path)}  {image_path.name}\n", encoding="utf-8")

    timeout = s.gm_timeout_ms
    post_identify = int(s.gm_post_identify_wait_ms)

    with playwright_glyph_context(s) as context:
        page = context.new_page()
        page.set_default_timeout(timeout)
        try:
            page.goto(s.gm_base_url, wait_until="load", timeout=timeout)

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

            if post_identify > 0:
                page.wait_for_timeout(post_identify)

            # Do not use locator.count() == 0 immediately — the button may appear only after Identify.
            download_btn = page.locator("#downloadLinesBtn")
            try:
                download_btn.wait_for(state="attached", timeout=timeout)
            except PlaywrightTimeout:
                download_btn = page.get_by_role(
                    "button", name=re.compile(r"Download Lines File", re.IGNORECASE)
                )
                download_btn.wait_for(state="attached", timeout=timeout)

            dloc = download_btn.first
            _wait_for_download_control(page, dloc, timeout_ms=timeout)

            try:
                dloc.scroll_into_view_if_needed(timeout=min(30_000, timeout))
            except PlaywrightTimeout:
                pass

            with page.expect_download(timeout=timeout) as dl_info:
                dloc.click(force=True)
            download = dl_info.value
            suggested = download.suggested_filename or f"{job_id}-lines.xml"
            out_path = out_dir / suggested
            download.save_as(str(out_path))

            if not out_path.is_file() or out_path.stat().st_size == 0:
                raise GlyphMachinaError(
                    f"Glyph Machina download saved nothing usable at {out_path}. "
                    "Try again, confirm Identify Lines completed, or use Skip Glyph Machina with a saved lines XML."
                )

            return out_path

        except PlaywrightTimeout as e:
            raise GlyphMachinaError(
                f"Glyph Machina UI timed out after {timeout} ms ({e}). "
                "Increase TRANSCRIBER_SHELL_GM_TIMEOUT_MS, TRANSCRIBER_SHELL_GM_POST_IDENTIFY_WAIT_MS, "
                "check network, or use Skip automated lineation with existing XML."
            ) from e
