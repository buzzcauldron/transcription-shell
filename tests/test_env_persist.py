from __future__ import annotations

from pathlib import Path

from transcriber_shell.env_persist import merge_dotenv


def test_merge_dotenv_preserves_comments_and_other_keys(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text(
        "# header\n"
        "FOO=bar\n"
        "ANTHROPIC_API_KEY=old\n"
        "OTHER=1\n",
        encoding="utf-8",
    )
    merge_dotenv(
        p,
        {
            "ANTHROPIC_API_KEY": "newsecret",
            "OPENAI_API_KEY": "",
            "GOOGLE_API_KEY": "",
            "TRANSCRIBER_SHELL_OLLAMA_BASE_URL": "",
        },
    )
    text = p.read_text(encoding="utf-8")
    assert "FOO=bar" in text
    assert "OTHER=1" in text
    assert "ANTHROPIC_API_KEY=newsecret" in text
    assert "old" not in text


def test_merge_dotenv_creates_file(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    merge_dotenv(
        p,
        {"ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "", "GOOGLE_API_KEY": "", "TRANSCRIBER_SHELL_OLLAMA_BASE_URL": ""},
    )
    assert p.is_file()
    assert "ANTHROPIC_API_KEY=k" in p.read_text(encoding="utf-8")


def test_merge_dotenv_no_empty_file_when_missing_and_all_empty(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    assert not p.exists()
    merge_dotenv(
        p,
        {
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "GOOGLE_API_KEY": "",
            "TRANSCRIBER_SHELL_OLLAMA_BASE_URL": "",
        },
    )
    assert not p.exists()


def test_merge_dotenv_clearing_only_managed_keys_truncates_existing_file(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("ANTHROPIC_API_KEY=secret\n", encoding="utf-8")
    merge_dotenv(
        p,
        {
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "GOOGLE_API_KEY": "",
            "TRANSCRIBER_SHELL_OLLAMA_BASE_URL": "",
        },
    )
    assert p.read_text(encoding="utf-8") == ""


def test_merge_dotenv_writes_lineation_backend(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    merge_dotenv(
        p,
        {
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "GOOGLE_API_KEY": "",
            "TRANSCRIBER_SHELL_OLLAMA_BASE_URL": "",
            "TRANSCRIBER_SHELL_LINEATION_BACKEND": "kraken",
        },
    )
    assert "TRANSCRIBER_SHELL_LINEATION_BACKEND=kraken" in p.read_text(encoding="utf-8")
