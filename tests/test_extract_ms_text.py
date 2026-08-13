from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_ms_text.py"
SPEC = importlib.util.spec_from_file_location("extract_ms_text", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_natural_key_orders_numeric_page_ids() -> None:
    pages = [Path("f100.yaml"), Path("f20.yaml"), Path("f3.yaml")]
    assert sorted(pages, key=MODULE.natural_key) == [
        Path("f3.yaml"),
        Path("f20.yaml"),
        Path("f100.yaml"),
    ]


def _write_yaml(path: Path, text: str) -> None:
    path.write_text(
        "transcriptionOutput:\n"
        "  segments:\n"
        f"    - text: {text!r}\n",
        encoding="utf-8",
    )


def test_prefer_expanded_uses_sidecar_over_yaml(tmp_path: Path) -> None:
    artifacts = tmp_path / "03_artifacts_2500" / "p0001"
    artifacts.mkdir(parents=True)
    yaml_path = artifacts / "p0001_transcription.yaml"
    _write_yaml(yaml_path, "diplomaticus")
    expanded_dir = tmp_path / "04_expanded"
    expanded_dir.mkdir()
    (expanded_dir / "p0001_expanded.txt").write_text("expandedus et plenus", encoding="utf-8")

    text, source = MODULE.load_page_text(yaml_path, tmp_path / "03_artifacts_2500", prefer_expanded=True)
    assert source == "expanded"
    assert "expandedus" in text
    assert "diplomaticus" not in text


def test_prefer_expanded_falls_back_to_yaml(tmp_path: Path) -> None:
    artifacts = tmp_path / "03_artifacts_2500"
    artifacts.mkdir()
    yaml_path = artifacts / "p0002_transcription.yaml"
    _write_yaml(yaml_path, "solum diplomaticum")
    text, source = MODULE.load_page_text(yaml_path, artifacts, prefer_expanded=True)
    assert source == "yaml"
    assert "diplomaticum" in text
