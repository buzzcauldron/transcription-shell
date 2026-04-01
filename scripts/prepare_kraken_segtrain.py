"""Assemble Kraken segtrain ground truth from Glyph Machina artifact directories.

Crawls artifacts/gm-vatlib-* and artifacts/gm-deeds-* directories, finds the
source image for each, copies it alongside a fixed PageXML (imageFilename rewritten
to the local absolute path) into a single output directory, then prints the
ketos segtrain command to run.

Usage:
    python scripts/prepare_kraken_segtrain.py [options]

    # Minimal — uses defaults:
    python scripts/prepare_kraken_segtrain.py

    # Override output dir:
    python scripts/prepare_kraken_segtrain.py --out ~/src/kraken-gt

    # Dry run (report missing images, don't copy):
    python scripts/prepare_kraken_segtrain.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = REPO_ROOT / "artifacts"

# Search paths for source images, in priority order.
# The script walks each path's file tree to build a name→path index.
DEFAULT_IMAGE_SEARCH_PATHS = [
    Path("~/Projects/strigil/output/digi.vatlib.it/images").expanduser(),
    Path("~/Downloads/wetransfer_deeds-test-material_2026-01-20_0004").expanduser(),
]

DEFAULT_OUT_DIR = Path("~/src/kraken-vatlib-gt").expanduser()

# Existing deed GT dir with already-fixed absolute paths — included in segtrain command.
DEED_FINETUNE_GT = Path("~/src/deed-finetune-gt").expanduser()

# Model to fine-tune from.
DEFAULT_BASE_MODEL = Path("~/src/latin_documents/model_249.mlmodel").expanduser()

PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"

# Image filename stems (case-insensitive) that are not manuscript pages.
NON_MANUSCRIPT_STEMS = {
    "dvl_logo",
    "native",
    "cover",
    "ic_up",
    "iiif-logo-color",
    "iiif-logo-mono",
    "iiif-logo-white",
    "logo_viewer",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_image_index(search_paths: list[Path]) -> dict[str, Path]:
    """Return {filename_lower: absolute_path} for all files under search_paths."""
    index: dict[str, Path] = {}
    for root in search_paths:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file():
                key = p.name.lower()
                if key not in index:
                    index[key] = p
    return index


def _read_sha256_filename(sha256_path: Path) -> str | None:
    """Return the image filename recorded in a source_image.sha256 file."""
    try:
        line = sha256_path.read_text(encoding="utf-8").strip()
        # Format: "<checksum>  <filename>"
        parts = re.split(r"\s{2,}", line)
        if len(parts) >= 2:
            return parts[1].strip()
    except OSError:
        pass
    return None


def _fix_xml(xml_path: Path, image_path: Path) -> str:
    """Return XML text with Page@imageFilename replaced by the absolute image path."""
    ET.register_namespace("", PAGE_NS)
    tree = ET.parse(xml_path)
    root = tree.getroot()
    page = root.find(f"{{{PAGE_NS}}}Page")
    if page is None:
        # Try without namespace
        page = root.find("Page")
    if page is not None:
        page.set("imageFilename", str(image_path))
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _collect_artifact_dirs(artifacts_dir: Path) -> list[Path]:
    """Return all gm-vatlib-* and gm-deeds-* dirs that contain an XML file."""
    result = []
    for d in sorted(artifacts_dir.iterdir()):
        if not d.is_dir():
            continue
        if not (d.name.startswith("gm-vatlib-") or d.name.startswith("gm-deeds-")):
            continue
        xmls = list(d.glob("*.xml"))
        if xmls:
            result.append(d)
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR,
                   help=f"artifacts/ directory (default: {ARTIFACTS_DIR})")
    p.add_argument("--image-search-path", type=Path, action="append", dest="image_search_paths",
                   help="Extra image search path (repeatable; prepended before defaults)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR,
                   help=f"Output GT directory (default: {DEFAULT_OUT_DIR})")
    p.add_argument("--base-model", type=Path, default=DEFAULT_BASE_MODEL,
                   help=f"Kraken model to fine-tune from (default: {DEFAULT_BASE_MODEL})")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would be done without copying files")
    args = p.parse_args()

    search_paths = (args.image_search_paths or []) + DEFAULT_IMAGE_SEARCH_PATHS
    out_dir: Path = args.out.expanduser().resolve()

    print("Building image index …")
    image_index = _build_image_index(search_paths)
    print(f"  {len(image_index)} images indexed from {len(search_paths)} search paths")

    artifact_dirs = _collect_artifact_dirs(args.artifacts_dir.expanduser().resolve())
    print(f"\nFound {len(artifact_dirs)} artifact directories with XML")

    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    missing: list[str] = []

    for d in artifact_dirs:
        sha256_path = d / "source_image.sha256"
        image_name = _read_sha256_filename(sha256_path)
        if not image_name:
            missing.append(f"{d.name}: could not read source_image.sha256")
            continue

        if Path(image_name).stem.lower() in NON_MANUSCRIPT_STEMS:
            continue

        src_image = image_index.get(image_name.lower())
        if src_image is None:
            missing.append(f"{d.name}: image not found — {image_name}")
            continue

        # Pick the first XML (should only be one per artifact dir)
        xml_src = sorted(d.glob("*.xml"))[0]
        stem = Path(image_name).stem
        dst_image = out_dir / image_name
        dst_xml = out_dir / f"{stem}.xml"

        if args.dry_run:
            print(f"  [dry] {d.name} → {image_name}")
            ok += 1
            continue

        # Copy image (skip if already up-to-date by size)
        if not dst_image.exists() or dst_image.stat().st_size != src_image.stat().st_size:
            shutil.copy2(src_image, dst_image)

        # Write fixed XML
        try:
            xml_text = _fix_xml(xml_src, dst_image)
        except Exception as e:
            missing.append(f"{d.name}: XML parse error — {e}")
            continue

        dst_xml.write_text(xml_text, encoding="utf-8")
        ok += 1

    print(f"\n{'[dry-run] would assemble' if args.dry_run else 'Assembled'}: {ok} pairs → {out_dir}")

    if missing:
        print(f"\nSkipped ({len(missing)}):")
        for m in missing:
            print(f"  {m}")

    # Build ketos segtrain command
    deed_gt_xmls = ""
    if DEED_FINETUNE_GT.is_dir():
        n_deed = len(list(DEED_FINETUNE_GT.glob("*.xml")))
        if n_deed:
            deed_gt_xmls = f" \\\n  '{DEED_FINETUNE_GT}'/*.xml"
            print(f"\nDeed GT: {n_deed} XMLs at {DEED_FINETUNE_GT} (already have absolute paths)")

    model_arg = f"-i '{args.base_model}'" if args.base_model.exists() else "# base model not found — set -i"
    print(f"""
Run fine-tuning with:

  ketos segtrain \\
    {model_arg} \\
    -d mps \\
    --workers 0 \\
    -o ~/src/kraken-finetuned.mlmodel \\
    '{out_dir}'/*.xml{deed_gt_xmls}

After training, point the app at the new model:
  TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH=~/src/kraken-finetuned.mlmodel
""")

    if missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
