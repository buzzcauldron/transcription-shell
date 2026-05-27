"""Build train/val manifests for a Carolingian-focused computus HTR fine-tune.

Scans a curated set of Carolingian and early-medieval PageXML corpora, finds
XML+image pairs, deduplicates by stem, and writes train_manifest.txt /
val_manifest.txt for use with `ketos train -f page`.

Usage:
    python scripts/prepare_computus_htr_train.py [options]

    # Defaults (run on halxvi):
    python scripts/prepare_computus_htr_train.py

    # Override dirs:
    python scripts/prepare_computus_htr_train.py \\
        --corpora-dir /home/sethj/disk3/htr-corpora \\
        --out-dir /home/sethj/disk3/computus-gt

After running, launch training with scripts/train_computus_htr.sh.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

# ── Corpus configuration ──────────────────────────────────────────────────────

DEFAULT_CORPORA_DIR = Path("/home/sethj/disk3/htr-corpora")
DEFAULT_OUT_DIR = Path("/home/sethj/disk3/computus-gt")
MIN_PAIRS = 500

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# Corpora to include.  "full" means include every XML+image pair found.
# "all" is an alias — used for catmus-medieval where date-filtering would
# require parsing every XML header; conservative default is to include all.
CORPORA: list[dict] = [
    {"name": "caroline-minuscule",      "filter": "full"},
    {"name": "carolingian-latin-2025",  "filter": "full"},
    {"name": "carolingian-latin-vienna","filter": "full"},
    {"name": "paris-bible",             "filter": "full"},
    {"name": "eutyches",                "filter": "full"},
    {"name": "catmus-medieval",         "filter": "all"},   # conservative: include all
    {"name": "cremma-medieval-lat",     "filter": "full"},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_image(xml_path: Path) -> Path | None:
    """Return the image file paired with xml_path, or None if not found."""
    stem = xml_path.stem
    parent = xml_path.parent
    for ext in IMAGE_EXTS:
        candidate = parent / (stem + ext)
        if candidate.exists():
            return candidate
    return None


def scan_corpus(corpus_dir: Path, filter_mode: str) -> list[Path]:
    """Return all XML paths in corpus_dir that have a paired image.

    filter_mode is "full" or "all" — both currently include everything.
    Future date-aware filtering for catmus-medieval would go here.
    """
    if not corpus_dir.is_dir():
        return []

    xmls = sorted(corpus_dir.rglob("*.xml"))
    # Skip hidden/git internals and any chocomufin normalisation files
    xmls = [
        x for x in xmls
        if ".git" not in str(x) and "chocomufin" not in x.name
    ]

    paired: list[Path] = []
    for xml_path in xmls:
        if find_image(xml_path) is not None:
            paired.append(xml_path)

    return paired


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--corpora-dir",
        type=Path,
        default=DEFAULT_CORPORA_DIR,
        help=f"Root directory containing corpus subdirectories (default: {DEFAULT_CORPORA_DIR})",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Output directory for manifest files (default: {DEFAULT_OUT_DIR})",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for train/val split (default: 42)",
    )
    args = p.parse_args()

    corpora_dir: Path = args.corpora_dir.expanduser().resolve()
    out_dir: Path = args.out_dir.expanduser().resolve()

    if not corpora_dir.is_dir():
        sys.exit(f"ERROR: corpora-dir not found: {corpora_dir}")

    # ── Scan corpora ──────────────────────────────────────────────────────────

    all_xml: list[Path] = []
    seen_stems: set[str] = set()

    print(f"Corpora root:  {corpora_dir}")
    print(f"Output dir:    {out_dir}")
    print()
    print(f"{'Corpus':<32}  {'XML+img pairs':>14}  {'Deduplicated':>13}")
    print("-" * 64)

    for corpus_cfg in CORPORA:
        name: str = corpus_cfg["name"]
        filter_mode: str = corpus_cfg["filter"]

        corpus_path = corpora_dir / name
        found = scan_corpus(corpus_path, filter_mode)

        before = len(all_xml)
        added = 0
        for xml_path in found:
            stem = xml_path.stem
            if stem in seen_stems:
                continue
            seen_stems.add(stem)
            all_xml.append(xml_path)
            added += 1

        status = "(missing)" if not corpus_path.is_dir() else ""
        print(f"  {name:<30}  {len(found):>14,}  {added:>13,}  {status}")

    print("-" * 64)
    print(f"  {'TOTAL':<30}  {len(all_xml):>14,}")
    print()

    # ── Guard ─────────────────────────────────────────────────────────────────

    if len(all_xml) < MIN_PAIRS:
        sys.exit(
            f"ERROR: only {len(all_xml):,} pairs found; need at least {MIN_PAIRS:,}. "
            "Check that corpora are synced and paths are correct."
        )

    # ── Train/val split ───────────────────────────────────────────────────────

    rng = random.Random(args.seed)
    shuffled = list(all_xml)
    rng.shuffle(shuffled)

    split = int(len(shuffled) * 0.95)
    train_paths = shuffled[:split]
    val_paths = shuffled[split:]

    print(f"Split (seed={args.seed}):  train={len(train_paths):,}  val={len(val_paths):,}")
    print()

    # ── Write manifests ───────────────────────────────────────────────────────

    out_dir.mkdir(parents=True, exist_ok=True)

    train_manifest = out_dir / "train_manifest.txt"
    val_manifest = out_dir / "val_manifest.txt"

    train_manifest.write_text(
        "\n".join(str(x) for x in train_paths) + "\n", encoding="utf-8"
    )
    val_manifest.write_text(
        "\n".join(str(x) for x in val_paths) + "\n", encoding="utf-8"
    )

    print(f"Wrote: {train_manifest}")
    print(f"Wrote: {val_manifest}")
    print()
    print("Next step:")
    print(f"  bash scripts/train_computus_htr.sh")


if __name__ == "__main__":
    main()
