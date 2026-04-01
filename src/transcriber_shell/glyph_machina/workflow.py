"""Drive glyphmachina.com: upload pre-cropped image, Identify Lines, Download Lines File.

Selectors target the public UI as of 2026; the site may change — see docs/glyph-machina-automation.md.
"""

from __future__ import annotations

import errno
import hashlib
import re
import tempfile
import time
from pathlib import Path

from playwright.sync_api import Locator
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from transcriber_shell.config import Settings
from transcriber_shell.glyph_machina.browser import playwright_glyph_context

# Max pixels before downscaling for upload (4 MP keeps layout stable in browser)
_GM_MAX_PIXELS = 4_000_000


def _prepare_upload_image(image_path: Path) -> tuple[Path, Path | None]:
    """Return (upload_path, tmp_path). If image is oversized, write a scaled copy to tmp_path."""
    try:
        from PIL import Image
        im = Image.open(image_path)
        im.load()
        w, h = im.size
        pixels = w * h
        if pixels <= _GM_MAX_PIXELS:
            return image_path, None
        scale = (_GM_MAX_PIXELS / pixels) ** 0.5
        new_w, new_h = int(w * scale), int(h * scale)
        im_small = im.resize((new_w, new_h), Image.LANCZOS)
        suffix = image_path.suffix or ".jpg"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        im_small.save(tmp_path)
        return tmp_path, tmp_path
    except Exception:
        return image_path, None


class GlyphMachinaError(RuntimeError):
    pass


def _is_retryable_gm_error(exc: BaseException) -> bool:
    """One retry helps transient SPA/network slowness; not for missing files or bad downloads."""
    msg = str(exc).lower()
    if "timed out" in msg or "did not become ready" in msg:
        return True
    if "timeout" in msg and "glyph machina" in msg:
        return True
    if "network" in msg and "timeout" in msg:
        return True
    return False


def _checksum_image(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _wait_for_download_control(
    page: Page,
    dloc: Locator,
    *,
    timeout_ms: int,
    hidden_grace_s: float = 10.0,
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
        f"({timeout_ms} ms). Increase TRANSCRIBER_SHELL_GM_IDENTIFY_TIMEOUT_MS "
        "(or TRANSCRIBER_SHELL_GM_POST_IDENTIFY_WAIT_MS for the initial grace period), "
        "or use Skip automated lineation with a lines XML file."
    )


def _fetch_lines_xml_attempt(
    image_path: Path,
    job_id: str,
    *,
    settings: Settings,
    out_dir: Path,
) -> Path:
    """Single browser session: upload → Identify → download XML."""
    s = settings
    nav_timeout = s.gm_navigate_timeout_ms
    identify_timeout = s.gm_identify_timeout_ms
    post_identify = int(s.gm_post_identify_wait_ms)

    upload_path, tmp_path = _prepare_upload_image(image_path)
    try:
        with playwright_glyph_context(s) as context:
            page = context.new_page()
            page.set_default_timeout(nav_timeout)
            try:
                # "load" waits for all resources; Glyph Machina is a SPA and may never satisfy it on slow
                # networks. domcontentloaded is enough to interact (file input + buttons).
                page.goto(s.gm_base_url, wait_until="domcontentloaded", timeout=nav_timeout)

                file_input = page.locator('input[type="file"]').first
                file_input.wait_for(state="attached", timeout=nav_timeout)
                file_input.set_input_files(str(upload_path))
                page.wait_for_timeout(1_200)

                # Accept crop: pre-cropped images should fill the frame; button label on site is "Crop Image"
                crop = page.get_by_role("button", name="Crop Image")
                if crop.count() > 0:
                    crop.first.click()

                identify = page.get_by_role("button", name="Identify Lines")
                identify.wait_for(state="visible", timeout=nav_timeout)
                identify.click()

                if post_identify > 0:
                    page.wait_for_timeout(post_identify)

                # Do not use locator.count() == 0 immediately — the button may appear only after Identify.
                download_btn = page.locator("#downloadLinesBtn")
                try:
                    download_btn.wait_for(state="attached", timeout=identify_timeout)
                except PlaywrightTimeout:
                    download_btn = page.get_by_role(
                        "button", name=re.compile(r"Download Lines File", re.IGNORECASE)
                    )
                    download_btn.wait_for(state="attached", timeout=identify_timeout)

                dloc = download_btn.first
                _wait_for_download_control(page, dloc, timeout_ms=identify_timeout)

                try:
                    dloc.scroll_into_view_if_needed(timeout=min(30_000, identify_timeout))
                except Exception:
                    pass

                with page.expect_download(timeout=identify_timeout) as dl_info:
                    try:
                        dloc.click(force=True)
                    except Exception:
                        # Fallback: JS dispatch bypasses all visibility/interactability checks
                        dloc.dispatch_event("click")
                download = dl_info.value
                out_path = out_dir / "lines.xml"
                download.save_as(str(out_path))

                if not out_path.is_file() or out_path.stat().st_size == 0:
                    raise GlyphMachinaError(
                        f"Glyph Machina download saved nothing usable at {out_path}. "
                        "Try again, confirm Identify Lines completed, or use Skip Glyph Machina with a saved lines XML."
                    )

                return out_path

            except PlaywrightTimeout as e:
                raise GlyphMachinaError(
                    f"Glyph Machina UI timed out ({e}). "
                    f"Navigation budget: {nav_timeout} ms (TRANSCRIBER_SHELL_GM_NAVIGATE_TIMEOUT_MS). "
                    f"Identify/download budget: {identify_timeout} ms (TRANSCRIBER_SHELL_GM_IDENTIFY_TIMEOUT_MS). "
                    "Check network or use Skip automated lineation with existing XML."
                ) from e
            except OSError as e:
                if getattr(e, "errno", None) == errno.ETIMEDOUT or isinstance(e, TimeoutError):
                    raise GlyphMachinaError(
                        f"Glyph Machina: network-level timeout (errno {getattr(e, 'errno', '?')}): {e}. "
                        "Check connectivity to glyphmachina.com or use Skip automated lineation with existing XML."
                    ) from e
                raise
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def fetch_lines_xml(
    image_path: Path,
    job_id: str,
    settings: Settings | None = None,
) -> Path:
    """Upload ``image_path``, run Identify Lines, save downloaded lines XML under artifacts.

    Retries once on timeout-style failures (slow SPA / network). Raises GlyphMachinaError otherwise.
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

    for attempt in range(2):
        try:
            return _fetch_lines_xml_attempt(image_path, job_id, settings=s, out_dir=out_dir)
        except GlyphMachinaError as e:
            if attempt == 0 and _is_retryable_gm_error(e):
                time.sleep(15.0)
                continue
            raise
    raise RuntimeError("Glyph Machina: internal retry loop exited unexpectedly")
