#!/usr/bin/env python3
"""Split regularized latin-corpus-gt into phased retrain manifests.

Phase 1 (r6-core): medieval Latin GT only — retrains from gm-htr-r2 on a clean
foundation without the sloppy round5 shuffle or Bullinger script expansion.

Phase 2 (r7-full): full regularized corpus including Bullinger (Latin+German
early-modern correspondence), fine-tuned from r6-core with --resize union.

Reads metadata.jsonl produced by regularize_latin_htr_corpus.py.

Usage:
    python scripts/split_retrain_manifests.py \\
        --gt-dir /ocean/.../src/latin-corpus-gt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BULLINGER = "bullinger-extracted"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gt-dir", type=Path, required=True, help="latin-corpus-gt directory")
    args = p.parse_args()

    gt = args.gt_dir.expanduser().resolve()
    meta_path = gt / "metadata.jsonl"
    if not meta_path.is_file():
        sys.exit(f"metadata not found: {meta_path} — run regularize_latin_htr_corpus.py first")

    core_train: list[str] = []
    core_val: list[str] = []
    bull_train: list[str] = []
    bull_val: list[str] = []
    full_train: list[str] = []
    full_val: list[str] = []

    gt_train = gt_val = 0
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        xml = row["xml"]
        split = row["split"]
        corpus = row.get("corpus", "")
        is_gt = corpus.startswith("gt-")
        if split == "train":
            full_train.append(xml)
            if is_gt:
                gt_train += 1
            if corpus == BULLINGER:
                bull_train.append(xml)
            else:
                core_train.append(xml)
        elif split == "val":
            full_val.append(xml)
            if is_gt:
                gt_val += 1
            if corpus == BULLINGER:
                bull_val.append(xml)
            else:
                core_val.append(xml)

    def write(name: str, paths: list[str]) -> None:
        out = gt / name
        out.write_text("\n".join(paths) + ("\n" if paths else ""), encoding="utf-8")
        print(f"  {name}: {len(paths):,}")

    print(f"[split] writing phased manifests under {gt}")
    write("core_train_manifest.txt", core_train)
    write("core_val_manifest.txt", core_val)
    write("bullinger_train_manifest.txt", bull_train)
    write("bullinger_val_manifest.txt", bull_val)
    write("full_train_manifest.txt", full_train)
    write("full_val_manifest.txt", full_val)

    summary = {
        "core_train": len(core_train),
        "core_val": len(core_val),
        "bullinger_train": len(bull_train),
        "bullinger_val": len(bull_val),
        "full_train": len(full_train),
        "full_val": len(full_val),
        "human_gt_train": gt_train,
        "human_gt_val": gt_val,
        "retrain_phases": {
            "r6_core": {
                "base": "gm-htr-r2_best",
                "train": "core_train_manifest.txt",
                "val": "core_val_manifest.txt",
                "note": "Significant retrain: open corpora + human GT mss (Dropbox/akdeniz), no Bullinger.",
            },
            "r7_full": {
                "base": "gm-htr-r6-core_best",
                "train": "full_train_manifest.txt",
                "val": "full_val_manifest.txt",
                "resize": "union",
                "note": "Add Bullinger + full regularized corpus; expands charset.",
            },
        },
    }
    (gt / "retrain_plan.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[split] wrote retrain_plan.json")


if __name__ == "__main__":
    main()
