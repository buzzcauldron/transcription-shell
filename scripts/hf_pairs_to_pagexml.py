"""Convert HuggingFace-style PNG + .gt.txt line pairs to PAGE XML for ketos train.

Walks a directory tree looking for *.png files with a matching *.gt.txt
(same stem), and writes one *.xml (PAGE XML) per image, in-place.

Each XML contains a single TextLine with:
  - <Coords> boundary polygon (1px inset to pass ketos extract_polygons check)
  - <Baseline> at 80% of image height
  - <TextEquiv><Unicode> with the transcription

Usage:
    python scripts/hf_pairs_to_pagexml.py ~/src/htr-corpora/catmus-medieval
    python scripts/hf_pairs_to_pagexml.py ~/src/htr-corpora/tridis --workers 4
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def _convert_one(img_path: Path) -> tuple[Path, str]:
    """Convert a single PNG+.gt.txt pair. Returns (path, 'ok'|'skip'|'error')."""
    gt_path = img_path.with_suffix(".gt.txt")
    xml_path = img_path.with_suffix(".xml")

    if not gt_path.exists():
        return img_path, "skip"
    if xml_path.exists():
        return img_path, "skip"

    try:
        text = gt_path.read_text(encoding="utf-8").strip()
    except Exception:
        return img_path, "error"

    if not text:
        return img_path, "skip"

    try:
        from PIL import Image
        w, h = Image.open(img_path).size
    except Exception:
        return img_path, "error"

    text_esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    x1, y1, x2, y2 = 1, 1, w - 1, h - 1
    bly = max(min(int(h * 0.8), h - 2), 1)

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">\n'
        f'  <Page imageFilename="{img_path}" imageWidth="{w}" imageHeight="{h}">\n'
        f'    <TextRegion id="r1">'
        f'<Coords points="{x1},{y1} {x2},{y1} {x2},{y2} {x1},{y2}"/>\n'
        f'      <TextLine id="l1">\n'
        f'        <Coords points="{x1},{y1} {x2},{y1} {x2},{y2} {x1},{y2}"/>\n'
        f'        <Baseline points="{x1},{bly} {x2},{bly}"/>\n'
        f'        <TextEquiv><Unicode>{text_esc}</Unicode></TextEquiv>\n'
        f'      </TextLine>\n'
        f'    </TextRegion>\n'
        f'  </Page>\n'
        f'</PcGts>\n'
    )
    try:
        xml_path.write_text(xml, encoding="utf-8")
    except Exception:
        return img_path, "error"

    return img_path, "ok"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dirs", nargs="+", type=Path, help="Directories to scan recursively")
    p.add_argument("--workers", type=int, default=1, help="Parallel workers (default: 1)")
    args = p.parse_args()

    pairs: list[Path] = []
    for d in args.dirs:
        d = d.expanduser().resolve()
        if not d.is_dir():
            print(f"[SKIP] not a directory: {d}", file=sys.stderr)
            continue
        for img in sorted(d.rglob("*.png")):
            if img.with_suffix(".gt.txt").exists():
                pairs.append(img)

    if not pairs:
        print("No PNG+.gt.txt pairs found.")
        return

    print(f"Found {len(pairs):,} pairs. Converting…")
    ok = skip = err = 0

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(_convert_one, p): p for p in pairs}
            for i, fut in enumerate(as_completed(futs), 1):
                _, result = fut.result()
                if result == "ok":
                    ok += 1
                elif result == "skip":
                    skip += 1
                else:
                    err += 1
                if i % 5000 == 0:
                    print(f"  {i:,}/{len(pairs):,} …")
    else:
        for i, img in enumerate(pairs, 1):
            _, result = _convert_one(img)
            if result == "ok":
                ok += 1
            elif result == "skip":
                skip += 1
            else:
                err += 1
            if i % 5000 == 0:
                print(f"  {i:,}/{len(pairs):,} …")

    print(f"Done: {ok:,} written, {skip:,} skipped (already done / no text), {err} errors")


if __name__ == "__main__":
    main()
