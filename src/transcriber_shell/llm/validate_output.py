"""Validate YAML/JSON transcriptionOutput using vendored validate_schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Tuple

import yaml

from transcriber_shell.config import Settings
from transcriber_shell.protocol_paths import ensure_protocol_benchmark_on_path


def load_transcription_root(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict) and "transcriptionOutput" in data:
        out = data["transcriptionOutput"]
        return out if isinstance(out, dict) else None
    return None


def load_yaml_or_json_path(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".json",):
        return json.loads(text)
    return yaml.safe_load(text)


def validate_transcript_file(
    path: Path, settings: Settings | None = None
) -> Tuple[bool, list[str], list[str]]:
    ensure_protocol_benchmark_on_path(settings)
    from validate_schema import validate_transcription_output

    data = load_yaml_or_json_path(path)
    root = load_transcription_root(data)
    if root is None:
        return False, ["top-level transcriptionOutput object not found"], []
    return validate_transcription_output(root)
