from transcriber_shell.config import Settings
from transcriber_shell.llm.transcribe import _should_ollama_key_wall_fallback


def test_default_skips_ollama_fallback() -> None:
    assert _should_ollama_key_wall_fallback(Settings()) is False


def test_htr_first_never_falls_back_to_qwen() -> None:
    s = Settings(require_htr_before_llm=True, ollama_key_wall_fallback=True)
    assert _should_ollama_key_wall_fallback(s) is False


def test_opt_in_only_for_llm_only_runs() -> None:
    s = Settings(require_htr_before_llm=False, ollama_key_wall_fallback=True)
    assert _should_ollama_key_wall_fallback(s) is True
