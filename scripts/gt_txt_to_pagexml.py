"""Convert PNG + .gt.txt line image pairs to minimal PageXML for ketos 7 train.

ketos 7 drops the -f path format for recognition training. This script
wraps each pre-cropped line image in a PageXML file so it can be compiled
to binary (.arrow) and fed to ketos train -f binary.

Usage:
    python gt_txt_to_pagexml.py ~/src/gm-hf-gt/train ~/src/gm-hf-gt/train-xml
    python gt_txt_to_pagexml.py ~/src/gm-hf-gt/test  ~/src/gm-hf-gt/test-xml
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
ET.register_namespace("", NS)


def convert_pair(png_path: Path, gt_path: Path, out_dir: Path) -> None:
    text = gt_path.read_text(encoding="utf-8").strip()
    out_xml = out_dir / (png_path.stem + ".xml")
    if out_xml.exists():
        return

    with Image.open(png_path) as im:
        w, h = im.size

    # Use w-1, h-1: ketos rejects coords >= image dimensions (strict check)
    W, H = w - 1, h - 1
    baseline_y = min(round(h * 0.8), H)

    root = ET.Element(f"{{{NS}}}PcGts")
    page = ET.SubElement(root, f"{{{NS}}}Page",
                         imageFilename=str(png_path.resolve()),
                         imageWidth=str(w), imageHeight=str(h))
    region = ET.SubElement(page, f"{{{NS}}}TextRegion", id="r1")
    ET.SubElement(region, f"{{{NS}}}Coords",
                  points=f"0,0 {W},0 {W},{H} 0,{H}")
    tl = ET.SubElement(region, f"{{{NS}}}TextLine", id="l1")
    ET.SubElement(tl, f"{{{NS}}}Coords",
                  points=f"0,0 {W},0 {W},{H} 0,{H}")
    ET.SubElement(tl, f"{{{NS}}}Baseline",
                  points=f"0,{baseline_y} {W},{baseline_y}")
    equiv = ET.SubElement(tl, f"{{{NS}}}TextEquiv")
    ET.SubElement(equiv, f"{{{NS}}}Unicode").text = text

    ET.ElementTree(root).write(str(out_xml), xml_declaration=True,
                               encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path, help="Directory with PNG + .gt.txt pairs")
    p.add_argument("dst", type=Path, help="Output directory for XML files")
    args = p.parse_args()

    args.dst.mkdir(parents=True, exist_ok=True)
    pngs = sorted(args.src.glob("*.png"))
    print(f"Converting {len(pngs)} pairs: {args.src} → {args.dst}")
    done = skipped = 0
    for png in pngs:
        gt = png.with_suffix(".gt.txt")
        if not gt.exists():
            skipped += 1
            continue
        convert_pair(png, gt, args.dst)
        done += 1
        if done % 500 == 0:
            print(f"  {done}/{len(pngs)}")
    print(f"Done: {done} converted, {skipped} skipped (no .gt.txt)")


if __name__ == "__main__":
    main()
