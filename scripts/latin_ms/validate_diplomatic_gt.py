#!/usr/bin/env python3
"""Validate a diplomatic GT txt against its PAGE XML — line counts must match."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: validate_diplomatic_gt.py <stem-or-txt-path>", file=sys.stderr)
        return 1

    arg = Path(sys.argv[1])
    # Accept stem, _diplomatic.txt path, or directory/stem
    if arg.suffix == ".txt":
        txt_path = arg
        stem = arg.stem.replace("_diplomatic", "")
    else:
        stem = arg.name if arg.is_dir() else str(arg)
        stem = stem.replace("_diplomatic", "")
        txt_path = arg.parent / f"{stem}_diplomatic.txt" if arg.is_dir() else \
                   Path(f"ground_truth/diplomatic/{stem}_diplomatic.txt")

    if not txt_path.exists():
        print(f"ERROR: {txt_path} not found", file=sys.stderr)
        return 1

    # Find matching GT XML
    search_dirs = [
        Path("ground_truth/pages"),
        Path.home() / "latin-ms-workspace/training/combined_gt",
        Path.home() / "Library/CloudStorage/Dropbox/Seth/Mac/Documents/manuscript-data",
    ]
    xml_path = None
    for d in search_dirs:
        candidate = d / f"{stem}.xml"
        if candidate.exists():
            xml_path = candidate
            break

    txt_lines = [l for l in txt_path.read_text(encoding="utf-8").splitlines() if l.strip() != "" or True]
    # Count non-empty lines (allow trailing blank)
    txt_line_count = sum(1 for l in txt_lines if l.strip())

    print(f"  stem:  {stem}")
    print(f"  txt:   {txt_path} ({txt_line_count} non-empty lines)")

    ok = True
    if xml_path:
        tree = ET.parse(xml_path)
        xml_lines = tree.findall(".//{*}TextLine")
        xml_count = len(xml_lines)
        print(f"  xml:   {xml_path} ({xml_count} TextLines)")
        if txt_line_count != xml_count:
            print(f"  MISMATCH: txt has {txt_line_count} lines, xml has {xml_count} TextLines", file=sys.stderr)
            ok = False
        else:
            print(f"  line count OK ({xml_count})")
    else:
        print(f"  WARNING: no GT XML found for {stem} — skipping line count check")

    if ok:
        print("  VALID")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
