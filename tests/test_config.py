from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from transcriber_shell.config import Settings


def test_resolved_model_prefers_default_model():
    s = Settings(
        default_model="custom-model",
        anthropic_model="claude-x",
        openai_model="gpt-x",
        gemini_model="gem-x",
    )
    assert s.resolved_model("anthropic") == "custom-model"
    assert s.resolved_model("openai") == "custom-model"


def test_resolved_model_per_provider_without_override():
    s = Settings(default_model=None, anthropic_model="a", openai_model="b", gemini_model="g")
    assert s.resolved_model("anthropic") == "a"
    assert s.resolved_model("openai") == "b"


def test_resolved_model_ollama():
    s = Settings(default_model=None, ollama_model="llava-phi3")
    assert s.resolved_model("ollama") == "llava-phi3"


def test_lines_xml_xsd_and_require_text_line_defaults():
    s = Settings()
    assert s.lines_xml_xsd is None
    assert s.xml_require_text_line is True
    assert s.skip_lines_xml_validation is False
    assert s.continue_on_lineation_failure is False
    assert s.xml_only is False
    assert s.gm_auto_install_browser is True


def test_default_lineation_backend_is_glyph_machina():
    env = os.environ.copy()
    env.pop("TRANSCRIBER_SHELL_LINEATION_BACKEND", None)
    env.pop("LINEATION_BACKEND", None)
    with patch.dict(os.environ, env, clear=True):
        s = Settings()
    assert s.lineation_backend == "glyph_machina"


def test_lines_xml_xsd_expands_tilde_from_env():
    with patch.dict(os.environ, {"TRANSCRIBER_SHELL_LINES_XML_XSD": "~/schemas/page.xsd"}, clear=False):
        s = Settings()
    assert s.lines_xml_xsd is not None
    assert s.lines_xml_xsd == Path.home() / "schemas" / "page.xsd"


def test_xml_require_text_line_can_be_false():
    s = Settings(xml_require_text_line=False)
    assert s.xml_require_text_line is False
