"""Integration-style tests for run_pipeline with LLM and schema validation mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from transcriber_shell.config import Settings
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
            return_value="transcriptionOutput: {}\n",
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
    assert res.transcription_yaml_path.name == "transcription.yaml"
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
