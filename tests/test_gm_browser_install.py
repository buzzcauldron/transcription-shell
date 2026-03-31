"""Playwright Chromium ensure step for Glyph Machina."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from transcriber_shell.config import Settings
from transcriber_shell.glyph_machina import browser as gm_browser


@pytest.fixture(autouse=True)
def reset_browser_install_flag() -> None:
    gm_browser._browser_install_done = False
    yield
    gm_browser._browser_install_done = False


def _mock_playwright_cm(executable_path: str) -> MagicMock:
    p = MagicMock()
    p.chromium.executable_path = executable_path
    cm = MagicMock()
    cm.__enter__.return_value = p
    cm.__exit__.return_value = False
    return cm


def test_ensure_playwright_skips_cli_when_auto_install_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("TRANSCRIBER_SHELL_GM_AUTO_INSTALL_BROWSER", "false")
    exe = tmp_path / "chrome"
    exe.write_bytes(b"")
    with patch("subprocess.run") as m:
        with patch(
            "transcriber_shell.glyph_machina.browser.sync_playwright",
            return_value=_mock_playwright_cm(str(exe)),
        ):
            gm_browser.ensure_playwright_chromium(settings=Settings())
        m.assert_not_called()


def test_ensure_playwright_runs_cli_install_once(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("TRANSCRIBER_SHELL_GM_AUTO_INSTALL_BROWSER", raising=False)
    exe = tmp_path / "chrome"
    ok = MagicMock()
    ok.returncode = 0

    def fake_run(_cmd, *, check=False):
        exe.write_bytes(b"fake")
        return ok

    with patch("subprocess.run", side_effect=fake_run) as m:
        with patch(
            "transcriber_shell.glyph_machina.browser.sync_playwright",
            return_value=_mock_playwright_cm(str(exe)),
        ):
            gm_browser.ensure_playwright_chromium(settings=Settings())
            gm_browser.ensure_playwright_chromium(settings=Settings())
    assert m.call_count == 1


def test_ensure_playwright_raises_on_cli_install_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRANSCRIBER_SHELL_GM_AUTO_INSTALL_BROWSER", raising=False)
    bad = MagicMock()
    bad.returncode = 1
    with patch("subprocess.run", return_value=bad):
        with pytest.raises(RuntimeError, match="Playwright Chromium install failed"):
            gm_browser.ensure_playwright_chromium(settings=Settings())


def test_ensure_raises_when_executable_still_missing_after_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.delenv("TRANSCRIBER_SHELL_GM_AUTO_INSTALL_BROWSER", raising=False)
    missing = str(tmp_path / "nope-chrome")
    ok = MagicMock()
    ok.returncode = 0
    with patch("subprocess.run", return_value=ok):
        with patch(
            "transcriber_shell.glyph_machina.browser.sync_playwright",
            return_value=_mock_playwright_cm(missing),
        ):
            with pytest.raises(RuntimeError, match="Chromium executable not found"):
                gm_browser.ensure_playwright_chromium(settings=Settings())
