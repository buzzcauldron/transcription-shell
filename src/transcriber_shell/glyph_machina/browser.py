"""Playwright browser lifecycle for Glyph Machina."""

from __future__ import annotations

import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from playwright.sync_api import BrowserContext, Playwright, sync_playwright

from transcriber_shell.config import Settings

_install_lock = threading.Lock()
_browser_install_done = False


def _require_chromium_executable(p: Playwright) -> None:
    exe = Path(p.chromium.executable_path)
    if not exe.exists():
        raise RuntimeError(
            "Chromium executable not found. Install manually:\n"
            f"  {sys.executable} -m playwright install chromium"
        )


def _install_chromium_cli_once(settings: Settings) -> None:
    """Run ``python -m playwright install chromium`` before opening Playwright (once per process).

    Pip does not bundle browser binaries; this step is idempotent when Chromium is already present.
    """
    global _browser_install_done
    if not settings.gm_auto_install_browser:
        return
    if _browser_install_done:
        return
    with _install_lock:
        if _browser_install_done:
            return
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "Playwright Chromium install failed. Install manually:\n"
                f"  {sys.executable} -m playwright install chromium"
            )
        _browser_install_done = True


def ensure_playwright_chromium(*, settings: Settings | None = None) -> None:
    """Ensure Chromium is available: optional CLI install, then verify via Playwright."""
    s = settings or Settings()
    _install_chromium_cli_once(s)
    with sync_playwright() as p:
        _require_chromium_executable(p)


@contextmanager
def playwright_glyph_context(
    settings: Settings | None = None,
) -> Generator[BrowserContext, None, None]:
    """Yield a BrowserContext — ephemeral browser or persistent profile (cookies / logins)."""
    s = settings or Settings()
    _install_chromium_cli_once(s)
    with sync_playwright() as p:
        _require_chromium_executable(p)
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
