from __future__ import annotations

from transcriber_shell.gui_discovery import find_cli_tools


def test_find_cli_tools_returns_dict() -> None:
    found = find_cli_tools()
    assert isinstance(found, dict)
