#!/usr/bin/env python3
"""Convert protocol transcriptionOutput YAML → TEI XML for expand-diplomatic.

Usage:
    yaml_to_tei.py <input.yaml> [<output.xml>]
    yaml_to_tei.py --dir <artifacts_dir> --out-dir <tei_dir>

One <p> per segment; uncertainty tokens preserved verbatim.
"""
import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml")

TEI_NS = "http://www.tei-c.org/ns/1.0"
ET.register_namespace("", TEI_NS)


def _segments_text(data: dict) -> list[str]:
    out = data.get("transcriptionOutput", data)
    segs = out.get("segments", [])
    return [s.get("text", "") for s in segs if s.get("text")]


def yaml_to_tei(src: Path, dst: Path) -> None:
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", nargs="?", help="single YAML file")
    ap.add_argument("output", nargs="?", help="output XML file")
    ap.add_argument("--dir", help="directory of *_transcription.yaml files")
    ap.add_argument("--out-dir", help="destination directory for TEI XMLs")
    args = ap.parse_args()

    if args.dir:
        src_dir = Path(args.dir)
        dst_dir = Path(args.out_dir) if args.out_dir else src_dir.parent / "tei"
        for src in sorted(src_dir.rglob("*_transcription.yaml")):
            stem = src.stem.replace("_transcription", "")
            dst = dst_dir / f"{stem}_tei.xml"
            yaml_to_tei(src, dst)
            print(f"  {src.name} → {dst.name}")
    elif args.input:
        src = Path(args.input)
        dst = Path(args.output) if args.output else src.with_suffix(".tei.xml")
        yaml_to_tei(src, dst)
        print(f"  {src.name} → {dst.name}")
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
