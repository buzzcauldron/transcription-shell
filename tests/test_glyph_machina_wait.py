"""Unit tests for Glyph Machina wait helpers (no live browser)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from transcriber_shell.glyph_machina.workflow import (
    GlyphMachinaError,
    _is_retryable_gm_error,
    _wait_for_download_control,
)


def test_wait_for_download_control_visible_returns() -> None:
    page = MagicMock()
    page.wait_for_timeout = MagicMock()
    loc = MagicMock()
    loc.is_enabled.return_value = True
    loc.is_visible.return_value = True

    _wait_for_download_control(page, loc, timeout_ms=5000, hidden_grace_s=6.0)


def test_wait_for_download_control_hidden_enabled_after_grace() -> None:
    page = MagicMock()
    page.wait_for_timeout = MagicMock()
    loc = MagicMock()
    loc.is_enabled.return_value = True
    loc.is_visible.return_value = False

    _wait_for_download_control(page, loc, timeout_ms=5000, hidden_grace_s=0.02)


def test_is_retryable_gm_error() -> None:
    assert _is_retryable_gm_error(
        GlyphMachinaError("Glyph Machina UI timed out after 600000 ms (x)")
    )
    assert _is_retryable_gm_error(
        GlyphMachinaError("download control (#downloadLinesBtn) did not become ready in time")
    )
    assert not _is_retryable_gm_error(
        GlyphMachinaError("Glyph Machina download saved nothing usable at /tmp/x")
    )


def test_wait_for_download_control_timeout() -> None:
    page = MagicMock()
    page.wait_for_timeout = MagicMock()
    loc = MagicMock()
    loc.is_enabled.return_value = False
    loc.is_visible.return_value = False

    with pytest.raises(GlyphMachinaError, match="did not become ready"):
        _wait_for_download_control(page, loc, timeout_ms=50, hidden_grace_s=1.0)
