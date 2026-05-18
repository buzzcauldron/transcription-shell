"""Download mzzhang2014/glyph_machina training data from HuggingFace.

Saves parquet files to artifacts/gm-training-data/ and optionally
exports image+XML pairs compatible with ketos segtrain.

Usage:
    python download_gm_training_data.py
    python download_gm_training_data.py --out ~/gm-training-data --export-xml
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import urllib.request
from pathlib import Path


HF_REPO = "mzzhang2014/glyph_machina"
HF_BASE = f"https://huggingface.co/datasets/{HF_REPO}/resolve/main"

PARQUET_FILES = [
    "data/train-00000-of-00002.parquet",
    "data/train-00001-of-00002.parquet",
    "data/test-00000-of-00001.parquet",
]


def _download(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"  already exists: {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    print(f"  downloading {dest.name} ...", flush=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "transcription-shell/1.0"})
        with urllib.request.urlopen(req) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk = 1 << 20  # 1 MB
            while True:
                data = resp.read(chunk)
                if not data:
                    break
                f.write(data)
                downloaded += len(data)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r  {pct:3d}% ({downloaded // (1 << 20)} / {total // (1 << 20)} MB)", end="", flush=True)
            print()
        tmp.rename(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def export_xml_pairs(parquet_path: Path, out_dir: Path) -> int:
    """Write each row as image.jpg + PageXML for ketos segtrain."""
    try:
        import pyarrow.parquet as pq
        from PIL import Image
        import xml.etree.ElementTree as ET
    except ImportError as e:
        print(f"  export requires pyarrow and pillow: {e}", file=sys.stderr)
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    table = pq.read_table(str(parquet_path))
    exported = 0
    for i, row in enumerate(table.to_pylist()):
        img_bytes = row.get("image", {})
        if isinstance(img_bytes, dict):
            img_bytes = img_bytes.get("bytes", b"")
        if not img_bytes:
            continue
        stem = f"gm_{parquet_path.stem}_{i:05d}"
        img_path = out_dir / f"{stem}.jpg"
        xml_path = out_dir / f"{stem}.xml"
        if img_path.exists() and xml_path.exists():
            exported += 1
            continue
        try:
            im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            im.save(img_path, quality=92)
        except Exception as e:
            print(f"  row {i}: image error: {e}", file=sys.stderr)
            continue
        # Build minimal PageXML from baselines if available
        baselines = row.get("baselines") or row.get("lines") or []
        w, h = im.size
        ns = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
        ET.register_namespace("", ns)
        root = ET.Element(f"{{{ns}}}PcGts")
        page = ET.SubElement(root, f"{{{ns}}}Page",
                             imageFilename=str(img_path.resolve()),
                             imageWidth=str(w), imageHeight=str(h))
        region = ET.SubElement(page, f"{{{ns}}}TextRegion", id="r1",
                               custom="type {type:paragraph;}")
        ET.SubElement(region, f"{{{ns}}}Coords", points=f"0,0 {w},0 {w},{h} 0,{h}")
        for j, bl in enumerate(baselines):
            if not bl:
                continue
            tl = ET.SubElement(region, f"{{{ns}}}TextLine", id=f"l{j+1}",
                                custom="type {type:default;}")
            pts_str = " ".join(f"{x},{y}" for x, y in bl) if isinstance(bl[0], (list, tuple)) else str(bl)
            ET.SubElement(tl, f"{{{ns}}}Baseline", points=pts_str)
            ET.SubElement(tl, f"{{{ns}}}Coords", points=pts_str)
        tree = ET.ElementTree(root)
        tree.write(str(xml_path), xml_declaration=True, encoding="utf-8")
        exported += 1
    return exported


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=Path("artifacts/gm-training-data"),
                   help="Output directory for parquet files [default: artifacts/gm-training-data]")
    p.add_argument("--export-xml", action="store_true",
                   help="Also export image+PageXML pairs for ketos segtrain")
    p.add_argument("--xml-out", type=Path, default=None,
                   help="Where to write image+XML pairs [default: --out/pagexml/]")
    args = p.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {HF_REPO} → {args.out}")
    for rel_path in PARQUET_FILES:
        url = f"{HF_BASE}/{rel_path}"
        dest = args.out / Path(rel_path).name
        _download(url, dest)

    if args.export_xml:
        xml_out = args.xml_out or args.out / "pagexml"
        print(f"\nExporting image+XML pairs → {xml_out}")
        total = 0
        for pq_file in args.out.glob("*.parquet"):
            n = export_xml_pairs(pq_file, xml_out)
            print(f"  {pq_file.name}: {n} pairs")
            total += n
        print(f"Total: {total} pairs exported")
        print(f"\nUse with segtrain_rounds.py --vatlib-gt {xml_out}")

    print("\nDone.")


if __name__ == "__main__":
    main()
