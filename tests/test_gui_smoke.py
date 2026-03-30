"""GUI module loads without starting tkinter mainloop."""

from __future__ import annotations


def test_gui_module_has_main() -> None:
    from transcriber_shell.gui import TranscriberGui, main

    assert callable(main)
    assert TranscriberGui is not None
