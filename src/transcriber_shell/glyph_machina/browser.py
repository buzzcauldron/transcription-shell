"""Playwright browser lifecycle for Glyph Machina."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from playwright.sync_api import BrowserContext, sync_playwright

from transcriber_shell.config import Settings


@contextmanager
def playwright_glyph_context(
    settings: Settings | None = None,
) -> Generator[BrowserContext, None, None]:
    """Yield a BrowserContext — ephemeral browser or persistent profile (cookies / logins)."""
    s = settings or Settings()
    with sync_playwright() as p:
        if s.gm_persistent_profile:
            user_data = s.gm_user_data_dir.expanduser().resolve()
            user_data.mkdir(parents=True, exist_ok=True)
            context = p.chromium.launch_persistent_context(
                str(user_data),
                headless=s.gm_headless,
                accept_downloads=True,
            )
            try:
                yield context
            finally:
                context.close()
        else:
            browser = p.chromium.launch(headless=s.gm_headless)
            try:
                context = browser.new_context(accept_downloads=True)
                try:
                    yield context
                finally:
                    context.close()
            finally:
                browser.close()
