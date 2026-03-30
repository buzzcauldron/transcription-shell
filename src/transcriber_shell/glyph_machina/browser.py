"""Playwright browser lifecycle for Glyph Machina."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from playwright.sync_api import Browser, Playwright, sync_playwright

from transcriber_shell.config import Settings


@contextmanager
def playwright_browser(settings: Settings | None = None) -> Generator[tuple[Playwright, Browser], None, None]:
    s = settings or Settings()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=s.gm_headless)
        try:
            yield p, browser
        finally:
            browser.close()
