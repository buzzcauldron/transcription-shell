#!/usr/bin/env python3
"""Convert accepted/edited CoMMA line records into PAGE XML training files.

Reads adjudicated.jsonl (from comma_review.py) and confident.jsonl (from
comma_filter.py), writes one PAGE XML per accepted/edited line alongside its
crop image, and produces manifest.txt and metadata.jsonl for ketos train.

Usage:
    python scripts/comma_to_gt.py \\
        --adjudicated /ocean/.../comma-rerecognition/adjudicated.jsonl \\
        --confident   /ocean/.../comma-rerecognition/filtered/confident.jsonl \\
        --crops-root  /ocean/.../comma-rerecognition/pilot \\
        --out-dir     /ocean/.../comma-adjudicated-gt \\
        [--min-text-len 5]

FIREWALL: refuses to write into any path containing 'htr-corpora' or
'latin-corpus-gt'.

Notes on the output:
  - split is always "train"; these lines are never written to val.
  - human_gt is False (pseudo-GT from automated recognition + human accept).
  - The PAGE XML uses the same format as pagexml_line_strip.py.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Firewall
# ---------------------------------------------------------------------------

FIREWALL_TOKENS = ("htr-corpora", "latin-corpus-gt")


def _assert_safe_output(path: Path) -> None:
    s = str(path.resolve()).lower()
    for tok in FIREWALL_TOKENS:
        if tok in s:
            sys.exit(
                f"Refusing to write into training tree path: {path}\n"
                "Use a separate comma-adjudicated-gt directory instead."
            )


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# PAGE XML writer (mirrors pagexml_line_strip.py)
# ---------------------------------------------------------------------------

def _write_page_xml(img_path: Path, text: str, xml_path: Path) -> None:
    """Write a minimal PAGE XML for a single line-strip image."""
    from PIL import Image

    w, h = Image.open(img_path).size
    x1, y1, x2, y2 = 1, 1, max(w - 1, 1), max(h - 1, 1)
    bl = max(min(int(h * 0.8), h - 2), 1)
    pts = f"{x1},{y1} {x2},{y1} {x2},{y2} {x1},{y2}"
    ap = html.escape(str(img_path.resolve()), quote=True)
    txt = html.escape(text.strip(), quote=False)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">\n'
        f'  <Page imageFilename="{ap}" imageWidth="{w}" imageHeight="{h}">\n'
        f'    <TextRegion id="r1"><Coords points="{pts}"/>\n'
        f'      <TextLine id="l1">\n'
        f'        <Coords points="{pts}"/>\n'
        f'        <Baseline points="{x1},{bl} {x2},{bl}"/>\n'
        f'        <TextEquiv><Unicode>{txt}</Unicode></TextEquiv>\n'
        f'      </TextLine>\n'
        f'    </TextRegion>\n'
        f'  </Page>\n'
        f'</PcGts>\n'
    )
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(xml, encoding="utf-8")


# ---------------------------------------------------------------------------
# Line deduplication key
# ---------------------------------------------------------------------------

def _line_key(row: dict) -> tuple:
    return (row.get("ms_id"), row.get("page_idx"), row.get("line_idx"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--adjudicated", type=Path, default=None,
                    help="adjudicated.jsonl from comma_review.py (optional)")
    ap.add_argument("--confident", type=Path, default=None,
                    help="confident.jsonl from comma_filter.py (optional)")
    ap.add_argument("--crops-root", type=Path, required=True,
                    help="Root directory for crop_path values "
                         "(the --out-dir used in comma_recognition_pass.py)")
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="Output GT directory (must NOT be under htr-corpora or latin-corpus-gt)")
    ap.add_argument("--min-text-len", type=int, default=5,
                    help="Skip lines whose text is shorter than this (default 5)")
    args = ap.parse_args()

    if not args.adjudicated and not args.confident:
        ap.error("At least one of --adjudicated or --confident is required.")

    out_dir = args.out_dir.expanduser().resolve()
    _assert_safe_output(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    crops_root = args.crops_root.expanduser().resolve()

    # -----------------------------------------------------------------------
    # Collect lines, adjudicated first (takes priority over confident)
    # -----------------------------------------------------------------------
    seen_keys: set[tuple] = set()
    sources: list[tuple[dict, str]] = []  # (row, source_label)

    if args.adjudicated:
        adj_path = args.adjudicated.expanduser().resolve()
        for row in _load_jsonl(adj_path):
            action = row.get("action", "")
            if action not in ("accept", "edit"):
                continue
            key = _line_key(row)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            sources.append((row, "adjudicated"))

    if args.confident:
        conf_path = args.confident.expanduser().resolve()
        for row in _load_jsonl(conf_path):
            key = _line_key(row)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            # confident.jsonl uses our_text; normalise to text field
            if "text" not in row and "our_text" in row:
                row = dict(row)
                row["text"] = row["our_text"]
            sources.append((row, "confident"))

    print(f"[to-gt] {len(sources)} candidate lines from inputs")

    # -----------------------------------------------------------------------
    # Write PAGE XML for each line
    # -----------------------------------------------------------------------
    xml_paths: list[str] = []
    meta_rows: list[dict] = []
    skipped = 0
    written = 0

    for row, source in sources:
        text = (row.get("text") or "").strip()
        if len(text) < args.min_text_len:
            skipped += 1
            continue

        crop_rel = row.get("crop_path") or ""
        if not crop_rel:
            skipped += 1
            continue

        img_path = crops_root / crop_rel
        if not img_path.is_file():
            print(f"  [warn] crop not found, skipping: {img_path}", file=sys.stderr)
            skipped += 1
            continue

        ms_id = str(row.get("ms_id") or "unknown")
        page_idx = int(row.get("page_idx") or 0)
        line_idx = int(row.get("line_idx") or 0)

        safe_ms = re.sub(r"[^\w.-]+", "_", ms_id)[:80]
        xml_name = f"page_{page_idx:03d}_line_{line_idx:03d}.xml"
        img_name = f"page_{page_idx:03d}_line_{line_idx:03d}.png"
        ms_out_dir = out_dir / safe_ms
        ms_out_dir.mkdir(parents=True, exist_ok=True)

        # Copy/link the crop image next to the XML
        out_img = ms_out_dir / img_name
        if not out_img.is_file():
            try:
                import shutil
                shutil.copy2(str(img_path), str(out_img))
            except OSError as exc:
                print(f"  [warn] could not copy crop {img_path}: {exc}", file=sys.stderr)
                skipped += 1
                continue

        xml_path = ms_out_dir / xml_name
        try:
            _write_page_xml(out_img, text, xml_path)
        except Exception as exc:
            print(f"  [warn] PAGE XML write failed for {xml_path}: {exc}", file=sys.stderr)
            skipped += 1
            continue

        rel_xml = str(xml_path.relative_to(out_dir))
        xml_paths.append(str(xml_path))
        meta_rows.append(
            {
                "xml": rel_xml,
                "corpus": "comma-adjudicated",
                "split": "train",
                "human_gt": False,
                "script": None,
            }
        )
        written += 1

    # -----------------------------------------------------------------------
    # manifest.txt (absolute paths, one per line, for ketos train -t)
    # -----------------------------------------------------------------------
    manifest_path = out_dir / "manifest.txt"
    manifest_path.write_text("\n".join(xml_paths) + "\n", encoding="utf-8")

    # -----------------------------------------------------------------------
    # metadata.jsonl
    # -----------------------------------------------------------------------
    meta_path = out_dir / "metadata.jsonl"
    with meta_path.open("w", encoding="utf-8") as fh:
        for row in meta_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(
        f"[to-gt] written={written}  skipped={skipped}  "
        f"out={out_dir}"
    )
    print(f"[to-gt] manifest: {manifest_path}  ({written} entries)")
    print(f"[to-gt] metadata: {meta_path}")


if __name__ == "__main__":
    main()
