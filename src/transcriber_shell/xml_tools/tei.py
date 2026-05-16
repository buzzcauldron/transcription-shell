"""Convert protocol transcriptionOutput YAML → TEI XML.

The canonical logic; scripts/latin_ms/yaml_to_tei.py delegates here.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

TEI_NS = "http://www.tei-c.org/ns/1.0"
ET.register_namespace("", TEI_NS)


def _segments_text(data: dict) -> list[str]:
    out = data.get("transcriptionOutput", data)
    segs = out.get("segments", [])
    return [s.get("text", "") for s in segs if s.get("text")]


def yaml_to_tei(src: Path, dst: Path) -> None:
    """Convert a single protocol YAML file to a minimal TEI XML document."""
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    texts = _segments_text(raw)
    root = ET.Element(f"{{{TEI_NS}}}TEI")
    body = ET.SubElement(ET.SubElement(root, f"{{{TEI_NS}}}text"), f"{{{TEI_NS}}}body")
    for t in texts:
        p = ET.SubElement(body, f"{{{TEI_NS}}}p")
        p.text = t
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(dst), encoding="unicode", xml_declaration=True)


def convert_dir(artifacts_dir: Path, out_dir: Path) -> list[tuple[Path, Path]]:
    """Convert all *_transcription.yaml files in artifacts_dir to TEI XML in out_dir.

    Skips files inside conventional backup directories whose names end in
    ``.tridis_era``, ``.flash`` / ``.flash_era``, ``.bak``, or contain
    ``.backup``. Without this filter, snapshot backups inside the artifacts
    tree silently shadow the current YAMLs (same stem → same TEI output
    filename, last-write-wins).

    When the same stem appears multiple times even after backup filtering,
    the most recently modified YAML wins.

    Returns list of (src, dst) pairs written.
    """
    def _is_backup(p: Path) -> bool:
        for part in p.parts:
            low = part.lower()
            if low.endswith((".tridis_era", ".flash", ".flash_era", ".bak", ".backup")):
                return True
            if ".backup" in low:
                return True
        return False

    candidates: dict[str, Path] = {}
    for src in artifacts_dir.rglob("*_transcription.yaml"):
        if _is_backup(src.relative_to(artifacts_dir)):
            continue
        stem = src.stem.replace("_transcription", "")
        prev = candidates.get(stem)
        if prev is None or src.stat().st_mtime > prev.stat().st_mtime:
            candidates[stem] = src

    pairs: list[tuple[Path, Path]] = []
    for stem in sorted(candidates):
        src = candidates[stem]
        dst = out_dir / f"{stem}_tei.xml"
        yaml_to_tei(src, dst)
        pairs.append((src, dst))
    return pairs
