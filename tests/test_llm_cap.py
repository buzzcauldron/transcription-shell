from __future__ import annotations

from transcriber_shell.config import Settings
from transcriber_shell.llm.errors import is_llm_cap_error, skip_retries_on_llm_cap


def test_is_llm_cap_error() -> None:
    assert is_llm_cap_error("Error code: 429 - tokens per day (TPD) limit")
    assert is_llm_cap_error("429 RESOURCE_EXHAUSTED free_tier")
    assert not is_llm_cap_error("Cannot reach Ollama at http://127.0.0.1:11434")


def test_skip_retries_only_in_correct_mode() -> None:
    class E(Exception):
        status_code = 429

    cap = E("429")
    assert skip_retries_on_llm_cap(Settings(llm_mode="correct"), cap) is True
    assert skip_retries_on_llm_cap(Settings(llm_mode="full"), cap) is False
    assert skip_retries_on_llm_cap(Settings(llm_mode="off"), cap) is False


def test_cap_trip_skips_later_pages(monkeypatch) -> None:
    from transcriber_shell.llm import errors as err

    err.reset_llm_cap_trip()
    monkeypatch.delenv("TRANSCRIBER_SHELL_LLM_SKIP_ON_CAP", raising=False)
    monkeypatch.delenv("STREAM_JOB_DIR", raising=False)
    monkeypatch.delenv("TRANSCRIBER_SHELL_JOB_DIR", raising=False)
    assert err.llm_cap_tripped() is False
    err.trip_llm_cap()
    assert err.llm_cap_tripped() is True
    err.reset_llm_cap_trip()
    monkeypatch.setenv("TRANSCRIBER_SHELL_LLM_SKIP_ON_CAP", "1")
    assert err.llm_cap_tripped() is True
    err.reset_llm_cap_trip()


def test_trip_llm_cap_stamps_job_marker(tmp_path, monkeypatch) -> None:
    from transcriber_shell.llm import errors as err

    err.reset_llm_cap_trip()
    monkeypatch.delenv("TRANSCRIBER_SHELL_LLM_SKIP_ON_CAP", raising=False)
    monkeypatch.setenv("STREAM_JOB_DIR", str(tmp_path))
    err.trip_llm_cap()
    marker = tmp_path / "status" / "llm.CAP"
    assert marker.is_file()
    assert marker.read_text(encoding="utf-8").strip()
    err.reset_llm_cap_trip()
