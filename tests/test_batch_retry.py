from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from transcriber_shell.config import Settings
from transcriber_shell.pipeline.batch import (
    has_successful_transcription,
    run_batch,
)


def test_has_successful_transcription_true_when_yaml_validates(tmp_path: Path) -> None:
    art = tmp_path / "artifacts"
    img = tmp_path / "job1.png"
    img.write_bytes(b"\x89PNG")
    p = art / "job1" / "job1_transcription.yaml"
    p.parent.mkdir(parents=True)
    p.write_text("transcriptionOutput: {}\n", encoding="utf-8")
    s = Settings(artifacts_dir=art)
    with patch(
        "transcriber_shell.pipeline.batch.validate_transcript_file",
        return_value=(True, [], []),
    ):
        assert has_successful_transcription("job1", img, settings=s) is True


def test_run_batch_skip_successful_skips_existing_job(tmp_path: Path) -> None:
    art = tmp_path / "artifacts"
    img = tmp_path / "ok.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    out = art / "ok" / "ok_transcription.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("transcriptionOutput: {}\n", encoding="utf-8")
    s = Settings(artifacts_dir=art)

    with (
        patch(
            "transcriber_shell.pipeline.batch.validate_transcript_file",
            return_value=(True, [], []),
        ),
        patch(
            "transcriber_shell.pipeline.batch.run_pipeline",
            side_effect=AssertionError("run_pipeline should not be called for skipped jobs"),
        ),
    ):
        rows = run_batch(
            [img],
            prompt_cfg={},
            provider="anthropic",
            model_override=None,
            skip_gm=False,
            lines_xml=None,
            lines_xml_dir=None,
            xsd_path=None,
            require_text_line=True,
            skip_successful=True,
            settings=s,
        )

    assert len(rows) == 1
    row = rows[0]
    assert row["ok"] is True
    assert row["skipped"] is True
    assert row["text_line_count"] is None
    assert row["transcription_segment_count"] == 0
    assert row["transcription_yaml"] == str(out.resolve())


def test_transcription_segment_count_reads_segments(tmp_path: Path) -> None:
    p = tmp_path / "t.yaml"
    p.write_text(
        'transcriptionOutput:\n  protocolVersion: "1.1.0"\n  metadata: {}\n'
        "  segments:\n    - { diplomaticText: a }\n    - { diplomaticText: b }\n",
        encoding="utf-8",
    )
    from transcriber_shell.pipeline.batch import transcription_segment_count

    assert transcription_segment_count(p) == 2
