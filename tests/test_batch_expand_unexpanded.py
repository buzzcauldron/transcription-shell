from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "computus" / "batch_expand_unexpanded.py"
SPEC = importlib.util.spec_from_file_location("batch_expand_unexpanded", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_rules_backend_expands_htr_only(tmp_path: Path) -> None:
    yaml_path = tmp_path / "p0001_transcription.yaml"
    yaml_path.write_text(
        "transcriptionOutput:\n"
        "  metadata:\n"
        "    notes: htr_only: on-machine Kraken; not protocol-compliant (no LLM correct)\n"
        "  segments:\n"
        "    - text: dñs\n",
        encoding="utf-8",
    )
    (tmp_path / ".needs_llm").write_text("htr_only\n", encoding="utf-8")
    assert MODULE.yaml_ready_for_expand(yaml_path, backend="rules") is True
    assert MODULE.yaml_ready_for_expand(yaml_path, backend="groq") is True
    assert MODULE.yaml_ready_for_expand(yaml_path, backend="local") is True
    assert MODULE.yaml_ready_for_expand(yaml_path, backend="gemini") is False


def test_llm_backend_skips_needs_llm_marker(tmp_path: Path) -> None:
    yaml_path = tmp_path / "p0002_transcription.yaml"
    yaml_path.write_text(
        "transcriptionOutput:\n  segments:\n    - text: diplomaticus\n",
        encoding="utf-8",
    )
    (tmp_path / ".needs_llm").write_text("pending\n", encoding="utf-8")
    assert MODULE.yaml_ready_for_expand(yaml_path, backend="anthropic") is False
    assert MODULE.yaml_ready_for_expand(yaml_path, backend="rules") is True


def test_job_artifacts_dir_prefers_2500(tmp_path: Path) -> None:
    job = tmp_path / "nypl_computus_text_3"
    (job / "03_artifacts").mkdir(parents=True)
    assert MODULE.job_artifacts_dir(job) == job / "03_artifacts"
    (job / "03_artifacts_2500").mkdir()
    assert MODULE.job_artifacts_dir(job) == job / "03_artifacts_2500"
