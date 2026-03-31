"""Integration-style tests for run_pipeline with LLM and schema validation mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from transcriber_shell.config import Settings
from transcriber_shell.glyph_machina.workflow import GlyphMachinaError
from transcriber_shell.llm.transcribe import TranscribeResult
from transcriber_shell.models.job import TranscribeJob
from transcriber_shell.pipeline.run import run_pipeline

MINIMAL_LINES_XML = """<?xml version="1.0"?>
<root xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15">
  <TextRegion>
    <TextLine id="l1"/>
  </TextRegion>
</root>
"""


@pytest.fixture
def tmp_artifacts(tmp_path: Path) -> Path:
    d = tmp_path / "artifacts"
    d.mkdir(parents=True)
    return d


def test_run_pipeline_skip_gm_success_with_mocks(
    tmp_path: Path, tmp_artifacts: Path
) -> None:
    lines = tmp_path / "lines.xml"
    lines.write_text(MINIMAL_LINES_XML, encoding="utf-8")
    image = tmp_path / "page.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    job = TranscribeJob(
        job_id="t1",
        image_path=image,
        prompt_cfg={"protocolVersion": "1.1.0", "sourcePageId": "p1"},
        provider="anthropic",
    )
    settings = Settings(artifacts_dir=tmp_artifacts)

    with (
        patch(
            "transcriber_shell.pipeline.run.run_transcribe",
            return_value=TranscribeResult("transcriptionOutput: {}\n", None),
        ) as mock_tx,
        patch(
            "transcriber_shell.pipeline.run.validate_transcript_file",
            return_value=(True, [], []),
        ) as mock_val,
    ):
        res = run_pipeline(
            job,
            skip_gm=True,
            lines_xml_path=lines,
            require_text_line=True,
            settings=settings,
        )

    assert res.errors == []
    assert res.lines_xml_path and res.lines_xml_path.resolve() == lines.resolve()
    assert res.transcription_yaml_path is not None
    assert res.transcription_yaml_path.name == "page_transcription.yaml"
    assert res.transcription_yaml_path.parent == (tmp_artifacts / "t1").resolve()
    mock_tx.assert_called_once()
    mock_val.assert_called_once()


def test_run_pipeline_skip_gm_fails_when_lines_xml_missing(tmp_path: Path) -> None:
    image = tmp_path / "page.jpg"
    image.write_bytes(b"\xff\xd8\xff")
    job = TranscribeJob(
        job_id="t2",
        image_path=image,
        prompt_cfg={},
        provider="anthropic",
    )
    res = run_pipeline(
        job,
        skip_gm=True,
        lines_xml_path=tmp_path / "nope.xml",
        settings=Settings(artifacts_dir=tmp_path / "a"),
    )
    assert any("Skip Glyph Machina requires" in e for e in res.errors)


def test_run_pipeline_timeout_error_includes_anthropic_timeout_hint(
    tmp_path: Path, tmp_artifacts: Path
) -> None:
    lines = tmp_path / "lines.xml"
    lines.write_text(MINIMAL_LINES_XML, encoding="utf-8")
    image = tmp_path / "page.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    job = TranscribeJob(
        job_id="t_timeout",
        image_path=image,
        prompt_cfg={"protocolVersion": "1.1.0", "sourcePageId": "p1"},
        provider="anthropic",
    )
    settings = Settings(artifacts_dir=tmp_artifacts)

    with patch(
        "transcriber_shell.pipeline.run.run_transcribe",
        side_effect=TimeoutError("timed out"),
    ):
        res = run_pipeline(
            job,
            skip_gm=True,
            lines_xml_path=lines,
            require_text_line=True,
            settings=settings,
        )

    assert len(res.errors) >= 1
    assert "TRANSCRIBER_SHELL_ANTHROPIC_TIMEOUT_S" in res.errors[0]


def test_run_pipeline_httpx_timeout_includes_network_hint(
    tmp_path: Path, tmp_artifacts: Path
) -> None:
    lines = tmp_path / "lines.xml"
    lines.write_text(MINIMAL_LINES_XML, encoding="utf-8")
    image = tmp_path / "page.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    job = TranscribeJob(
        job_id="t_httpx_timeout",
        image_path=image,
        prompt_cfg={"protocolVersion": "1.1.0", "sourcePageId": "p1"},
        provider="openai",
    )
    settings = Settings(artifacts_dir=tmp_artifacts)

    with patch(
        "transcriber_shell.pipeline.run.run_transcribe",
        side_effect=httpx.ReadTimeout("read timed out"),
    ):
        res = run_pipeline(
            job,
            skip_gm=True,
            lines_xml_path=lines,
            require_text_line=True,
            settings=settings,
        )

    assert len(res.errors) >= 1
    err = res.errors[0]
    assert "ReadTimeout" in err
    assert "lines_xml=" in err
    assert "TRANSCRIBER_SHELL_LLM_USE_PROXY" in err


def test_run_pipeline_skip_lines_xml_validation_bypasses_malformed_xml(
    tmp_path: Path, tmp_artifacts: Path
) -> None:
    """When skip_lines_xml_validation is True, malformed lines XML still reaches LLM (mocked)."""
    bad_xml = tmp_path / "lines.xml"
    bad_xml.write_text("<root><not_closed", encoding="utf-8")
    image = tmp_path / "page.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    job = TranscribeJob(
        job_id="t_skip_xml",
        image_path=image,
        prompt_cfg={"protocolVersion": "1.1.0", "sourcePageId": "p1"},
        provider="anthropic",
    )
    settings = Settings(artifacts_dir=tmp_artifacts)

    res_fail = run_pipeline(
        job,
        skip_gm=True,
        lines_xml_path=bad_xml,
        require_text_line=True,
        skip_lines_xml_validation=False,
        settings=settings,
    )
    assert res_fail.errors

    with (
        patch(
            "transcriber_shell.pipeline.run.run_transcribe",
            return_value=TranscribeResult("transcriptionOutput: {}\n", None),
        ),
        patch(
            "transcriber_shell.pipeline.run.validate_transcript_file",
            return_value=(True, [], []),
        ),
    ):
        res_ok = run_pipeline(
            job,
            skip_gm=True,
            lines_xml_path=bad_xml,
            require_text_line=True,
            skip_lines_xml_validation=True,
            settings=settings,
        )

    assert res_ok.errors == []
    assert any("Lines XML validation was skipped" in w for w in res_ok.warnings)
    assert res_ok.transcription_yaml_path is not None


def test_run_pipeline_lineation_failure_errors_when_continue_disabled(
    tmp_path: Path, tmp_artifacts: Path,
) -> None:
    image = tmp_path / "page.jpg"
    image.write_bytes(b"\xff\xd8\xff")
    job = TranscribeJob(
        job_id="t_line_fail",
        image_path=image,
        prompt_cfg={"protocolVersion": "1.1.0", "sourcePageId": "p1"},
        provider="anthropic",
    )
    settings = Settings(artifacts_dir=tmp_artifacts, continue_on_lineation_failure=False)

    with patch(
        "transcriber_shell.pipeline.run.fetch_lines_xml",
        side_effect=GlyphMachinaError("simulated GM failure"),
    ) as mock_fetch:
        res = run_pipeline(job, skip_gm=False, settings=settings)

    mock_fetch.assert_called_once()
    assert res.errors
    assert res.lines_xml_path is None
    assert res.transcription_yaml_path is None


def test_run_pipeline_lineation_failure_continues_when_continue_enabled(
    tmp_path: Path, tmp_artifacts: Path,
) -> None:
    image = tmp_path / "page.jpg"
    image.write_bytes(b"\xff\xd8\xff")
    job = TranscribeJob(
        job_id="t_line_cont",
        image_path=image,
        prompt_cfg={"protocolVersion": "1.1.0", "sourcePageId": "p1"},
        provider="anthropic",
    )
    settings = Settings(artifacts_dir=tmp_artifacts, continue_on_lineation_failure=True)

    with (
        patch(
            "transcriber_shell.pipeline.run.fetch_lines_xml",
            side_effect=GlyphMachinaError("simulated GM failure"),
        ) as mock_fetch,
        patch(
            "transcriber_shell.pipeline.run.run_transcribe",
            return_value=TranscribeResult("transcriptionOutput: {}\n", None),
        ) as mock_tx,
        patch(
            "transcriber_shell.pipeline.run.validate_transcript_file",
            return_value=(True, [], []),
        ),
    ):
        res = run_pipeline(job, skip_gm=False, settings=settings)

    mock_fetch.assert_called_once()
    mock_tx.assert_called_once()
    assert res.errors == []
    assert res.lines_xml_path is None
    assert res.text_line_count == 0
    assert res.transcription_yaml_path is not None
    assert any("Continuing without lines XML" in w for w in res.warnings)
    assert job.line_hint and "infer layout" in job.line_hint.lower()
