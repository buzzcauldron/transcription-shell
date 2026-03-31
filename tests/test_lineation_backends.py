"""Routing for mask / Kraken / Glyph Machina lineation in run_pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from transcriber_shell.config import Settings
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


def test_run_pipeline_mask_backend_mocked(
    tmp_path: Path, tmp_artifacts: Path
) -> None:
    lines = tmp_path / "lines.xml"
    lines.write_text(MINIMAL_LINES_XML, encoding="utf-8")
    image = tmp_path / "page.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    job = TranscribeJob(
        job_id="t_mask",
        image_path=image,
        prompt_cfg={"protocolVersion": "1.1.0", "sourcePageId": "p1"},
        provider="anthropic",
    )
    settings = Settings(artifacts_dir=tmp_artifacts, lineation_backend="mask")

    with (
        patch(
            "transcriber_shell.pipeline.run.run_transcribe",
            return_value=TranscribeResult("transcriptionOutput: {}\n", None),
        ),
        patch(
            "transcriber_shell.pipeline.run.validate_transcript_file",
            return_value=(True, [], []),
        ),
        patch(
            "transcriber_shell.pipeline.run.fetch_lines_xml_mask",
            return_value=lines,
        ) as mock_mask,
    ):
        res = run_pipeline(
            job,
            skip_gm=False,
            require_text_line=True,
            settings=settings,
        )

    assert res.errors == []
    mock_mask.assert_called_once()
    assert res.lines_xml_path and res.lines_xml_path.resolve() == lines.resolve()


def test_run_pipeline_kraken_backend_mocked(
    tmp_path: Path, tmp_artifacts: Path
) -> None:
    lines = tmp_path / "lines.xml"
    lines.write_text(MINIMAL_LINES_XML, encoding="utf-8")
    image = tmp_path / "page.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    job = TranscribeJob(
        job_id="t_k",
        image_path=image,
        prompt_cfg={"protocolVersion": "1.1.0", "sourcePageId": "p1"},
        provider="anthropic",
    )
    settings = Settings(artifacts_dir=tmp_artifacts, lineation_backend="kraken")

    with (
        patch(
            "transcriber_shell.pipeline.run.run_transcribe",
            return_value=TranscribeResult("transcriptionOutput: {}\n", None),
        ),
        patch(
            "transcriber_shell.pipeline.run.validate_transcript_file",
            return_value=(True, [], []),
        ),
        patch(
            "transcriber_shell.pipeline.run.fetch_lines_xml_kraken",
            return_value=lines,
        ) as mock_k,
    ):
        res = run_pipeline(job, skip_gm=False, require_text_line=True, settings=settings)

    assert res.errors == []
    mock_k.assert_called_once()
    assert res.lines_xml_path == lines.resolve()


def test_run_pipeline_glyph_machina_backend_mocked(
    tmp_path: Path, tmp_artifacts: Path
) -> None:
    lines = tmp_path / "lines.xml"
    lines.write_text(MINIMAL_LINES_XML, encoding="utf-8")
    image = tmp_path / "page.jpg"
    image.write_bytes(b"\xff\xd8\xff")

    job = TranscribeJob(
        job_id="t_gm",
        image_path=image,
        prompt_cfg={"protocolVersion": "1.1.0", "sourcePageId": "p1"},
        provider="anthropic",
    )
    settings = Settings(artifacts_dir=tmp_artifacts, lineation_backend="glyph_machina")

    with (
        patch(
            "transcriber_shell.pipeline.run.run_transcribe",
            return_value=TranscribeResult("transcriptionOutput: {}\n", None),
        ),
        patch(
            "transcriber_shell.pipeline.run.validate_transcript_file",
            return_value=(True, [], []),
        ),
        patch(
            "transcriber_shell.pipeline.run.fetch_lines_xml",
            return_value=lines,
        ) as mock_gm,
    ):
        res = run_pipeline(job, skip_gm=False, require_text_line=True, settings=settings)

    assert res.errors == []
    mock_gm.assert_called_once()
    assert res.lines_xml_path == lines.resolve()


def test_masks_to_lines_xml_writes_baseline(tmp_path: Path) -> None:
    from transcriber_shell.config import Settings
    from transcriber_shell.mask_lineation import masks_to_lines_xml

    img = tmp_path / "p.png"
    Image.new("RGB", (20, 10), color="white").save(img)

    pred = np.zeros((1, 5, 10), dtype=np.float32)
    pred[0, 2:4, :] = 1.0

    out = tmp_path / "out.xml"
    s = Settings(mask_threshold=0.5, lineation_credit_repo_url="https://example.com/credit")
    masks_to_lines_xml(img, pred, out, settings=s)
    text = out.read_text(encoding="utf-8")
    assert "Baseline" in text
    assert "line_0" in text
    assert "Credit:" in text
