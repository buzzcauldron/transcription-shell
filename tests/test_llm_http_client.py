from __future__ import annotations

from transcriber_shell.config import Settings
from transcriber_shell.llm.http_client import llm_httpx_client


def test_llm_httpx_client_none_when_proxy_disabled() -> None:
    s = Settings(llm_use_proxy=False, llm_http_proxy="http://proxy:8080")
    assert llm_httpx_client(s, timeout_seconds=60.0) is None


def test_llm_httpx_client_none_when_proxy_enabled_but_no_url() -> None:
    s = Settings(llm_use_proxy=True, llm_http_proxy=None)
    assert llm_httpx_client(s, timeout_seconds=60.0) is None


def test_llm_httpx_client_returns_client_when_enabled() -> None:
    s = Settings(llm_use_proxy=True, llm_http_proxy="http://127.0.0.1:9")
    c = llm_httpx_client(s, timeout_seconds=120.0)
    assert c is not None
    c.close()


def test_settings_parse_llm_proxy_flags() -> None:
    s = Settings(
        llm_use_proxy=True,
        llm_http_proxy="http://corp.local:3128",
    )
    assert s.llm_use_proxy is True
    assert s.llm_http_proxy == "http://corp.local:3128"


def test_settings_gm_persistent_defaults() -> None:
    s = Settings()
    assert s.gm_persistent_profile is False
    assert "transcriber-shell" in str(s.gm_user_data_dir)
