from __future__ import annotations

from pathlib import Path

from transcriber_shell.pipeline.transcription_paths import transcription_yaml_path


def test_transcription_yaml_path_uses_image_stem(tmp_path: Path) -> None:
    img = tmp_path / "my page.jpg"
    p = transcription_yaml_path(tmp_path / "artifacts", "job_x", img)
    assert p.name == "my page_transcription.yaml"
    assert p.parent == (tmp_path / "artifacts" / "job_x").resolve()
