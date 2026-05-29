"""Extract and convert structured table data from computus transcription YAMLs.

Segments with position 'table_row' or 'table_header' are expected to contain
pipe-delimited column text (as produced by the computus LLM prompt).  This
module converts those segments into structured table dicts, CSV, and JSON for
downstream analysis.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import yaml

_TABLE_POSITIONS = {"table_row", "table_header"}

# Matches the tableType annotation in a segment's notes field.
_TABLE_TYPE_RE = re.compile(r"tableType\s*:\s*(\S+)", re.IGNORECASE)

# Known computus table column schemas — used when the header row is absent.
KNOWN_COLUMN_SCHEMAS: dict[str, list[str]] = {
    "metonic_cycle": ["year", "epact", "concurrentes", "luna_xiv", "feria_paschalis"],
    "easter_table":  ["year", "epact", "luna_xiv", "feria_paschalis", "dies_paschae"],
    "calendar_kalends": ["KL", "feria", "luna", "festum"],
    "feria_regulares": ["month", "regulares", "concurrentes"],
    "indiction_cycle": ["year", "indictio", "cyclus_solaris", "cyclus_lunaris"],
}


def parse_pipe_row(text: str) -> list[str]:
    """Split a pipe-delimited table row into individual cell strings."""
    return [cell.strip() for cell in text.split("|")]


def _extract_table_type(seg: dict[str, Any]) -> str | None:
    notes = seg.get("notes") or ""
    m = _TABLE_TYPE_RE.search(notes)
    return m.group(1) if m else None


def extract_tables(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of table dicts extracted from a transcriptionOutput YAML.

    Each dict has:
      type        — tableType annotation (or 'unknown')
      columns     — list of column header strings (from table_header or KNOWN_COLUMN_SCHEMAS)
      rows        — list of rows, each a list of cell strings
      source_segs — list of original segment dicts that formed this table
    """
    out = data.get("transcriptionOutput", data)
    segs: list[dict[str, Any]] = out.get("segments", [])

    tables: list[dict[str, Any]] = []
    current_table: dict[str, Any] | None = None

    for seg in segs:
        pos = seg.get("position", "")
        if pos not in _TABLE_POSITIONS:
            if current_table is not None:
                tables.append(current_table)
                current_table = None
            continue

        text = (seg.get("text") or "").strip()
        cells = parse_pipe_row(text)

        if current_table is None:
            table_type = _extract_table_type(seg) or "unknown"
            current_table = {
                "type": table_type,
                "columns": KNOWN_COLUMN_SCHEMAS.get(table_type, []),
                "rows": [],
                "source_segs": [],
            }

        if pos == "table_header":
            current_table["columns"] = cells
        else:
            current_table["rows"].append(cells)

        current_table["source_segs"].append(seg)

        # Check if a later segment annotates the table type
        if current_table["type"] == "unknown":
            t = _extract_table_type(seg)
            if t:
                current_table["type"] = t
                if not current_table["columns"]:
                    current_table["columns"] = KNOWN_COLUMN_SCHEMAS.get(t, [])

    if current_table is not None:
        tables.append(current_table)

    return tables


def table_to_csv(table: dict[str, Any]) -> str:
    """Render a single table dict as CSV text."""
    buf = io.StringIO()
    w = csv.writer(buf)
    if table["columns"]:
        w.writerow(table["columns"])
    for row in table["rows"]:
        # Pad short rows to column width
        ncols = max(len(table["columns"]), len(row))
        padded = row + [""] * (ncols - len(row))
        w.writerow(padded)
    return buf.getvalue()


def tables_to_json(tables: list[dict[str, Any]], *, indent: int = 2) -> str:
    """Serialise extracted tables as JSON (drops source_segs for compactness)."""
    out = []
    for t in tables:
        out.append({
            "type": t["type"],
            "columns": t["columns"],
            "rows": t["rows"],
        })
    return json.dumps(out, ensure_ascii=False, indent=indent)


def extract_from_yaml_path(path: Path) -> list[dict[str, Any]]:
    """Load a transcription YAML file and return its extracted tables."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return extract_tables(data)
