"""Generate pseudo-labeled PageXML for HTR training from raw manuscript images.

Uses a trained Kraken HTR model (and optionally a seg model) to produce
per-line transcriptions, saving them as PageXML with TextEquiv elements
suitable for ketos train -f page.

Usage:
    python scripts/generate_pseudo_labels.py \\
        --htr-model ~/src/gm-hf-htr_best.mlmodel \\
        --seg-model ~/src/latin_documents/model_249.mlmodel \\
        --out ~/src/round2-gt \\
        ~/path/to/images/*.jpg

    # Multiple folders:
    python scripts/generate_pseudo_labels.py \\
        --htr-model ~/src/gm-hf-htr_best.mlmodel \\
        --seg-model ~/src/latin_documents/model_249.mlmodel \\
        --out ~/src/round2-gt \\
        ~/Dropbox/Seth/Bodlean,\\ Unsorted/*.jpg \\
        ~/Dropbox/Seth/Harley\\ 2252/*.pdf

Options:
    --htr-model PATH    Trained Kraken HTR model (required)
    --seg-model PATH    Kraken segmentation model (default: BLLA built-in)
    --out DIR           Output directory for PageXML files (default: ./round2-gt)
    --workers N         Parallel workers (default: 1)
    --dry-run           Print what would be processed, don't run
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _images_from_path(p: Path) -> list[Path]:
    """Resolve a path to a list of image files (handles PDFs by converting pages)."""
    if p.suffix.lower() == ".pdf":
        return _pdf_to_images(p)
    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"):
        return [p]
    return []


def _pdf_to_images(pdf_path: Path) -> list[Path]:
    """Convert PDF pages to PNG images alongside the PDF. Requires pdf2image / poppler."""
    try:
        from pdf2image import convert_from_path
    except ImportError:
        print(f"  [SKIP] pdf2image not installed — cannot process {pdf_path.name}")
        print("         pip install pdf2image  (also needs poppler)")
        return []
    out_dir = pdf_path.parent / f"{pdf_path.stem}_pages"
    out_dir.mkdir(exist_ok=True)
    pages = convert_from_path(str(pdf_path), dpi=200)
    paths = []
    for i, img in enumerate(pages):
        p = out_dir / f"page_{i:04d}.png"
        if not p.exists():
            img.save(str(p))
        paths.append(p)
    return paths


def _transcribe_image(img_path: Path, htr_model_path: Path, seg_model_path: Path | None) -> str | None:
    """
    Segment and transcribe one image with Kraken.
    Returns PageXML string with TextEquiv, or None on failure.
    """
    try:
        from PIL import Image as PILImage
        from kraken import blla, rpred
        from kraken.lib import models
        from kraken.lib.xml import XMLPage
    except ImportError as e:
        print(f"  [ERROR] kraken not importable: {e}")
        return None

    try:
        im = PILImage.open(str(img_path)).convert("RGB")
    except Exception as e:
        print(f"  [ERROR] cannot open image {img_path.name}: {e}")
        return None

    # Segment
    try:
        if seg_model_path:
            seg_model = models.load_any(str(seg_model_path))
            res = blla.segment(im, model=seg_model)
        else:
            res = blla.segment(im)
    except Exception as e:
        print(f"  [ERROR] segmentation failed for {img_path.name}: {e}")
        return None

    # Transcribe
    try:
        htr_model = models.load_any(str(htr_model_path))
        pred = rpred.rpred(htr_model, im, res)
        lines = list(pred)
    except Exception as e:
        print(f"  [ERROR] transcription failed for {img_path.name}: {e}")
        return None

    # Build PageXML
    w, h = im.size
    xml_lines = []
    for i, line in enumerate(lines):
        text = (line.prediction or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        bl = line.baseline or []
        if not bl:
            continue
        bl_str = " ".join(f"{x},{y}" for x, y in bl)
        boundary = line.boundary or []
        if boundary:
            coords_str = " ".join(f"{x},{y}" for x, y in boundary)
            coords_elem = f'<Coords points="{coords_str}"/>'
        else:
            coords_elem = f'<Coords points="0,0 {w},0 {w},{h} 0,{h}"/>'
        xml_lines.append(f"""      <TextLine id="l{i}">
        {coords_elem}
        <Baseline points="{bl_str}"/>
        <TextEquiv><Unicode>{text}</Unicode></TextEquiv>
      </TextLine>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">
  <Page imageFilename="{img_path.resolve()}" imageWidth="{w}" imageHeight="{h}">
    <TextRegion id="r1"><Coords points="0,0 {w},0 {w},{h} 0,{h}"/>
{"".join(xml_lines)}
    </TextRegion>
  </Page>
</PcGts>
"""
    return xml


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("images", nargs="+", type=Path, help="Image files or globs")
    p.add_argument("--htr-model", type=Path, required=True, help="Trained Kraken HTR .mlmodel")
    p.add_argument("--seg-model", type=Path, default=None, help="Kraken seg .mlmodel (default: built-in BLLA)")
    p.add_argument("--out", type=Path, default=Path("./round2-gt"), help="Output directory")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    htr_model = args.htr_model.expanduser().resolve()
    seg_model = args.seg_model.expanduser().resolve() if args.seg_model else None
    out_dir = args.out.expanduser().resolve()

    if not htr_model.exists():
        sys.exit(f"HTR model not found: {htr_model}")
    if seg_model and not seg_model.exists():
        sys.exit(f"Seg model not found: {seg_model}")

    # Gather images
    all_images: list[Path] = []
    for raw in args.images:
        resolved = raw.expanduser()
        imgs = _images_from_path(resolved)
        if not imgs:
            print(f"[SKIP] {raw} — not a supported image/PDF")
        else:
            all_images.extend(imgs)

    if not all_images:
        sys.exit("No images found.")

    print(f"Images:    {len(all_images)}")
    print(f"HTR model: {htr_model}")
    print(f"Seg model: {seg_model or '(built-in BLLA)'}")
    print(f"Output:    {out_dir}")
    if args.dry_run:
        for img in all_images[:10]:
            print(f"  would process: {img}")
        if len(all_images) > 10:
            print(f"  ... and {len(all_images)-10} more")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for i, img in enumerate(all_images):
        xml_out = out_dir / f"{img.stem}.xml"
        # Copy image alongside XML so ketos can find it
        img_out = out_dir / img.name
        print(f"[{i+1}/{len(all_images)}] {img.name}…", end=" ", flush=True)
        xml = _transcribe_image(img, htr_model, seg_model)
        if xml is None:
            print("FAILED")
            continue
        xml_out.write_text(xml, encoding="utf-8")
        if not img_out.exists():
            shutil.copy2(str(img), str(img_out))
        # Update imageFilename to point to local copy
        xml_out.write_text(
            xml_out.read_text().replace(str(img.resolve()), str(img_out)),
            encoding="utf-8",
        )
        print(f"OK ({xml_out.name})")
        ok += 1

    print(f"\n{ok}/{len(all_images)} images processed → {out_dir}/")
    print(f"\nNext: sync to CMU and run round-2 training:")
    print(f"  CMU_HOST=seth@akdeniz.lan.cmu.edu \\")
    print(f"  CMU_BASE_MODEL=~/src/gm-hf-htr_best.mlmodel \\")
    print(f"  LOCAL_GT_DIR={out_dir} \\")
    print(f"  ./scripts/htr_train_cmu.sh")


if __name__ == "__main__":
    main()
