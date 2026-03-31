from __future__ import annotations

import json

import pytest

from transcriber_shell import gui_state


def test_gui_state_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "gui_state.json"
    monkeypatch.setattr(gui_state, "gui_state_path", lambda: path)
    assert gui_state.load_gui_state() == {}
    payload = {
        "provider": "anthropic",
        "lineation_backend": "glyph_machina",
        "skip_gm": False,
    }
    gui_state.save_gui_state(payload)
    assert path.is_file()
    loaded = gui_state.load_gui_state()
    assert loaded["version"] == 1
    assert loaded["provider"] == "anthropic"
    assert loaded["lineation_backend"] == "glyph_machina"


def test_load_gui_state_invalid_json(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "gui_state.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(gui_state, "gui_state_path", lambda: path)
    assert gui_state.load_gui_state() == {}


def test_load_gui_state_wrong_version(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "gui_state.json"
    path.write_text(json.dumps({"version": 999, "provider": "x"}), encoding="utf-8")
    monkeypatch.setattr(gui_state, "gui_state_path", lambda: path)
    assert gui_state.load_gui_state() == {}
