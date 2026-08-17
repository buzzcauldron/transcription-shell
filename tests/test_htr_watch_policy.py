from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "computus" / "htr_watch_policy.py"
SPEC = importlib.util.spec_from_file_location("htr_watch_policy", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_coverage_ok_requires_90_percent() -> None:
    assert MODULE.coverage_ok(9, 0, 10) is True
    assert MODULE.coverage_ok(8, 0, 10) is False
    assert MODULE.coverage_ok(8, 1, 10) is True
    assert MODULE.coverage_ok(0, 0, 400) is False
    assert MODULE.coverage_ok(0, 0, 0) is False


def test_retryable_htr_errors() -> None:
    assert MODULE.is_retryable_htr_error(
        "error: Kraken model not found: /Users/halxiii/src/latin_documents/kraken-merged-seg.mlmodel_best.mlmodel"
    )
    assert MODULE.is_retryable_htr_error(
        "LLM transcription failed (anthropic): Cannot reach Ollama at http://127.0.0.1:11434"
    )
    assert not MODULE.is_retryable_htr_error("lineation: done (11.2s)\nhtr: done (2.6s)")
    assert not MODULE.is_retryable_htr_error(
        "LLM transcription failed (groq): Error code: 429 - tokens per day (TPD)"
    )
    assert MODULE.is_llm_cap_error(
        "LLM cleanup failed; kept on-machine HTR. Gemini: all models in cycle exhausted (429)"
    )


def test_foreign_os_model_path() -> None:
    mac = "/Users/halxiii/src/gm-seg.mlmodel"
    assert MODULE.is_foreign_os_model_path(mac, platform="linux") is True
    assert MODULE.is_foreign_os_model_path(mac, platform="darwin") is False
    assert MODULE.is_foreign_os_model_path("/home/seth/src/gm-seg.mlmodel", platform="linux") is False


def test_print_dump_google_books() -> None:
    names = [
        "noticesetextrai01goog_2Fnoticesetextrai01goog_jp2.zip_2Fnoticesetextrai01goog_0000_default.jpg"
    ]
    assert MODULE.looks_like_print_dump("clat_106", names) is True
    assert MODULE.looks_like_print_dump("clat_480_paris_bnf", ["f001_default.jpg"]) is False
    ia_ms = ["sb_878_cod_jp2.zip_0001.jpg", "sb_878_cod_jp2.zip_0002.jpg"]
    assert MODULE.looks_like_print_dump("bern_bb_441_cod", ia_ms) is False


def test_llm_only_for_autocorrect() -> None:
    assert MODULE.coerce_llm_mode(None) == "correct"
    assert MODULE.coerce_llm_mode("") == "correct"
    assert MODULE.coerce_llm_mode("off") == "off"
    assert MODULE.coerce_llm_mode("correct") == "correct"
    assert MODULE.coerce_llm_mode("full") == "correct"
    assert MODULE.coerce_llm_mode("gemini") == "correct"


def test_htr_queue_doneish_waits_for_autocorrect(tmp_path: Path) -> None:
    job = tmp_path / "ms"
    pages = job / "01_pages_2500"
    art = job / "03_artifacts_2500" / "p1"
    pages.mkdir(parents=True)
    art.mkdir(parents=True)
    for i in range(10):
        (pages / f"p{i:02d}.jpg").write_bytes(b"x")
    yaml = art / "p1_transcription.yaml"
    yaml.write_text(
        "transcriptionOutput:\n  metadata:\n    notes: htr_only: on-machine Kraken\n"
        "  segments:\n    - {text: anno}\n",
        encoding="utf-8",
    )
    assert MODULE.job_is_htr_queue_doneish(job, llm_mode="correct") is False
    assert MODULE.job_is_htr_queue_doneish(job, llm_mode="off") is False  # 1/10 yaml
    (job / "status").mkdir()
    (job / "status" / "llm.CAP").write_text("capped\n")
    # still 1 yaml of 10
    assert MODULE.job_is_htr_queue_doneish(job, llm_mode="correct") is False
    for i in range(10):
        d = job / "03_artifacts_2500" / f"p{i:02d}"
        d.mkdir(exist_ok=True)
        (d / f"p{i:02d}_transcription.yaml").write_text(
            "transcriptionOutput:\n  metadata:\n    notes: htr_only: on-machine Kraken\n"
            "  segments:\n    - {text: anno}\n",
            encoding="utf-8",
        )
    assert MODULE.job_is_htr_queue_doneish(job, llm_mode="correct") is True  # cap + yaml coverage
    (job / "status" / "llm.CAP").unlink()
    assert MODULE.job_is_htr_queue_doneish(job, llm_mode="correct") is False
    for i in range(10):
        d = job / "03_artifacts_2500" / f"p{i:02d}"
        (d / f"p{i:02d}_transcription.yaml").write_text(
            "transcriptionOutput:\n  metadata:\n    notes: llm_correct\n"
            "  segments:\n    - {text: anno}\n",
            encoding="utf-8",
        )
    assert MODULE.job_is_htr_queue_doneish(job, llm_mode="correct") is True


def test_expand_is_always_rules() -> None:
    assert MODULE.coerce_expand_backend("groq") == "rules"
    assert MODULE.coerce_expand_backend("local") == "rules"
    assert MODULE.coerce_expand_backend("gemini") == "rules"
    assert MODULE.coerce_expand_backend("rules") == "rules"
