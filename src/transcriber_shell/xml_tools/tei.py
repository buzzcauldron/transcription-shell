"""Convert protocol transcriptionOutput YAML → TEI XML.

The canonical logic; scripts/latin_ms/yaml_to_tei.py delegates here.

Table segments (position: table_row / table_header) are emitted as TEI
<table>/<row>/<cell> structures.  Pipe-delimited column text is split at '|'.
All other segment positions map to <p rend="{position}"> elements, except
'interlinear' which becomes <add place="above">.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

from transcriber_shell.xml_tools.tables import (
    _TABLE_POSITIONS,
    _extract_table_type,
    parse_pipe_row,
)

TEI_NS = "http://www.tei-c.org/ns/1.0"
ET.register_namespace("", TEI_NS)

_T = f"{{{TEI_NS}}}"

_POSITION_TO_REND: dict[str, str] = {
    "header":        "header",
    "footer":        "footer",
    "margin_left":   "marginLeft",
    "margin_right":  "marginRight",
    "margin_top":    "marginTop",
    "margin_bottom": "marginBottom",
    "footnote":      "footnote",
}


def _tei(tag: str, **attrib: str) -> ET.Element:
    return ET.Element(f"{_T}{tag}", **attrib)


def _sub(parent: ET.Element, tag: str, **attrib: str) -> ET.Element:
    return ET.SubElement(parent, f"{_T}{tag}", **attrib)


def _flush_table(body: ET.Element, pending: list[dict[str, Any]]) -> None:
    """Emit accumulated table segments as a TEI <table> block."""
    if not pending:
        return

    # Determine table type from the first annotated segment
    table_type = "unknown"
    for seg in pending:
        t = _extract_table_type(seg)
        if t:
            table_type = t
            break

    attribs: dict[str, str] = {}
    if table_type != "unknown":
        attribs["type"] = table_type

    tbl = _sub(body, "table", **attribs)

    for seg in pending:
        pos = seg.get("position", "")
        text = (seg.get("text") or "").strip()
        cells = parse_pipe_row(text)
        conf = seg.get("confidence", "")

        row_attribs: dict[str, str] = {}
        if pos == "table_header":
            row_attribs["role"] = "label"
        if conf:
            row_attribs["cert"] = conf

        row = _sub(tbl, "row", **row_attribs)
        for cell_text in cells:
            cell_attribs: dict[str, str] = {}
            if pos == "table_header":
                cell_attribs["role"] = "label"
            c = _sub(row, "cell", **cell_attribs)
            c.text = cell_text


def yaml_to_tei(src: Path, dst: Path) -> None:
    """Convert a single protocol YAML file to a TEI XML document."""
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    out = raw.get("transcriptionOutput", raw)
    segs: list[dict[str, Any]] = out.get("segments", [])
    meta = out.get("metadata", {})

    root = _tei("TEI")
    text_el = _sub(root, "text")
    body = _sub(text_el, "body")

    if meta:
        header = _sub(root, "teiHeader")
        fd = _sub(header, "fileDesc")
        ti = _sub(fd, "titleStmt")
        t = _sub(ti, "title")
        t.text = meta.get("sourcePageId") or src.stem
        pd = _sub(fd, "publicationStmt")
        p = _sub(pd, "p")
        p.text = (
            f"Transcription model: {meta.get('modelId', 'unknown')}. "
            f"Protocol: {meta.get('protocolVersion', '?')}."
        )
        root.insert(0, header)

    pending_table: list[dict[str, Any]] = []

    for seg in segs:
        pos = seg.get("position") or "body"
        text = (seg.get("text") or "").strip()
        conf = seg.get("confidence", "")

        if pos in _TABLE_POSITIONS:
            pending_table.append(seg)
            continue

        # Flush any open table before emitting a non-table segment
        if pending_table:
            _flush_table(body, pending_table)
            pending_table = []

        if not text:
            continue

        if pos == "interlinear":
            add = _sub(body, "add", place="above")
            if conf:
                add.set("cert", conf)
            add.text = text
        else:
            rend = _POSITION_TO_REND.get(pos, pos)
            p = _sub(body, "p", rend=rend)
            if conf:
                p.set("cert", conf)
            p.text = text

    # Flush any trailing table
    if pending_table:
        _flush_table(body, pending_table)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(dst), encoding="unicode", xml_declaration=True)


def convert_dir(artifacts_dir: Path, out_dir: Path) -> list[tuple[Path, Path]]:
    """Convert all *_transcription.yaml files in artifacts_dir to TEI XML in out_dir.

    Skips backup directories.  When the same stem appears multiple times,
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
