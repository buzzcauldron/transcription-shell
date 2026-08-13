#!/usr/bin/env python3
"""Assemble ketos train/val manifests for Anglicana legal fine-tune.

Scans gt-mss legal trees, normalizes nw-page-editor XML to PRImA, writes:
  latin-corpus-gt/anglicana_train_manifest.txt
  latin-corpus-gt/anglicana_val_manifest.txt
  latin-corpus-gt/anglicana_manifest_meta.jsonl

Also upserts matching rows into metadata.jsonl (script=anglicana).

Usage (on Bridges):
  python scripts/build_anglicana_gt.py \\
    --gt-mss-root /ocean/.../gt-mss \\
    --gt-dir /ocean/.../src/latin-corpus-gt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from normalize_legal_pagexml import normalize_xml  # noqa: E402
from pagexml_line_strip import find_image_for_xml  # noqa: E402

# (relative path under gt-mss, corpus id, default split mode)
SOURCES: list[tuple[str, str, str]] = [
    ("dropbox/Transcriptions/Done-lines", "gt-dropbox-done-lines", "train"),
    ("dropbox/Transcriptions/Coroners-Rolls", "gt-dropbox-coroners", "holdout"),
    ("dropbox/manuscript-data", "gt-dropbox-just1", "holdout"),
    ("local/val_holdout_gt", "gt-local-holdout", "holdout"),
    ("akdeniz/kraken-done-lines-gt", "gt-done-lines", "train"),
    ("akdeniz/kraken-cp40-gt", "gt-cp40", "holdout"),
    ("dropbox/Transcriptions/Validation-set", "gt-dropbox-validation", "val_only"),
]


@dataclass
class Page:
    xml: Path
    image: Path
    corpus: str
    split: str


def _stable_bucket(stem: str) -> float:
    h = hashlib.md5(stem.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def collect(gt_mss: Path, *, val_fraction: float, seed: int) -> list[Page]:
    pages: list[Page] = []
    seen_stems: set[str] = set()

    for rel, corpus, mode in SOURCES:
        root = gt_mss / rel
        if not root.is_dir():
            print(f"[skip] missing {root}")
            continue
        xmls = sorted(root.rglob("*.xml"))
        print(f"[scan] {rel}: {len(xmls)} xml")
        for xp in xmls:
            # Normalize (in place) — no-op rewrite into PRImA when possible
            out = normalize_xml(xp, in_place=True)
            if out is None:
                continue
            img = find_image_for_xml(out)
            if img is None:
                continue
            stem = out.stem.lower()
            if stem in seen_stems:
                continue
            seen_stems.add(stem)
            if mode == "val_only":
                split = "val"
            elif mode == "train":
                split = "train"
            else:
                split = "val" if _stable_bucket(stem) < val_fraction else "train"
            pages.append(Page(xml=out.resolve(), image=img.resolve(), corpus=corpus, split=split))
        print(f"  kept_unique={sum(1 for p in pages if p.corpus == corpus)}")

    # Ensure non-empty val: move up to 8 train pages if needed
    train = [p for p in pages if p.split == "train"]
    val = [p for p in pages if p.split == "val"]
    if len(val) < 5 and train:
        rng = random.Random(seed)
        need = min(8, max(0, 5 - len(val)), max(1, len(train) // 10))
        move = rng.sample(train, k=min(need, len(train)))
        for p in move:
            p.split = "val"
        train = [p for p in pages if p.split == "train"]
        val = [p for p in pages if p.split == "val"]
    print(f"[total] pages={len(pages)} train={len(train)} val={len(val)}")
    return pages


def write_manifests(pages: list[Page], gt_dir: Path) -> None:
    gt_dir.mkdir(parents=True, exist_ok=True)
    train = [str(p.xml) for p in pages if p.split == "train"]
    val = [str(p.xml) for p in pages if p.split == "val"]
    (gt_dir / "anglicana_train_manifest.txt").write_text("\n".join(train) + ("\n" if train else ""))
    (gt_dir / "anglicana_val_manifest.txt").write_text("\n".join(val) + ("\n" if val else ""))
    meta_path = gt_dir / "anglicana_manifest_meta.jsonl"
    with meta_path.open("w", encoding="utf-8") as fh:
        for p in pages:
            fh.write(
                json.dumps(
                    {
                        "xml": str(p.xml),
                        "image": str(p.image),
                        "corpus": p.corpus,
                        "split": p.split,
                        "script": "anglicana",
                        "human_gt": True,
                        "source": "gt-mss",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"[write] train={len(train)} val={len(val)} -> {gt_dir}")


def upsert_metadata(pages: list[Page], metadata_path: Path) -> None:
    """Replace prior anglicana human_gt rows; keep everything else."""
    keep: list[str] = []
    if metadata_path.is_file():
        for line in metadata_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("script") == "anglicana" and row.get("source") == "gt-mss":
                continue
            if row.get("corpus", "").startswith("gt-dropbox") and row.get("script") == "anglicana":
                continue
            keep.append(line)
    for p in pages:
        keep.append(
            json.dumps(
                {
                    "xml": str(p.xml),
                    "image": str(p.image),
                    "corpus": p.corpus,
                    "split": p.split,
                    "script": "anglicana",
                    "human_gt": True,
                    "source": "gt-mss",
                    "languages": ["latin"],
                },
                ensure_ascii=False,
            )
        )
    metadata_path.write_text("\n".join(keep) + "\n", encoding="utf-8")
    print(f"[metadata] upserted {len(pages)} anglicana rows -> {metadata_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gt-mss-root", type=Path, required=True)
    ap.add_argument("--gt-dir", type=Path, required=True)
    ap.add_argument("--val-fraction", type=float, default=0.12)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-train", type=int, default=40)
    args = ap.parse_args()

    pages = collect(args.gt_mss_root, val_fraction=args.val_fraction, seed=args.seed)
    train_n = sum(1 for p in pages if p.split == "train")
    if train_n < args.min_train:
        raise SystemExit(f"Too few train pages ({train_n} < {args.min_train})")
    write_manifests(pages, args.gt_dir)
    upsert_metadata(pages, args.gt_dir / "metadata.jsonl")


if __name__ == "__main__":
    main()
