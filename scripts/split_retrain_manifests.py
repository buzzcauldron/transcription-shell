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

# LAD 1.3–style Gothic book specialist (Paris Bible + CREMMA/HTRomance gothic literary).
GOTHIC_BIBLE_CORPORA = frozenset(
    {
        "paris-bible",
        "cremma-medieval-lat",
        "htromance-medieval-latin",
    }
)

# Louvre Abu Dhabi 2013.051 — LAD blind eval; text GT in paris-bible repo, no public images.
LAD_HOLDOUT_MS = "2013.051"


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
    gothic_train: list[str] = []
    gothic_val: list[str] = []

    gt_train = gt_val = 0
    paris_train = paris_val = 0
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        xml = row["xml"]
        split = row["split"]
        corpus = row.get("corpus", "")
        is_gt = corpus.startswith("gt-")
        is_gothic_bible = corpus in GOTHIC_BIBLE_CORPORA
        if split == "train":
            full_train.append(xml)
            if is_gt:
                gt_train += 1
            if corpus == BULLINGER:
                bull_train.append(xml)
            else:
                core_train.append(xml)
            if is_gothic_bible:
                gothic_train.append(xml)
                if corpus == "paris-bible":
                    paris_train += 1
        elif split == "val":
            full_val.append(xml)
            if is_gt:
                gt_val += 1
            if corpus == BULLINGER:
                bull_val.append(xml)
            else:
                core_val.append(xml)
            if is_gothic_bible:
                gothic_val.append(xml)
                if corpus == "paris-bible":
                    paris_val += 1

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
    write("gothic_bible_train_manifest.txt", gothic_train)
    write("gothic_bible_val_manifest.txt", gothic_val)

    lad_eval = {
        "ms": LAD_HOLDOUT_MS,
        "folios": "1r-20r",
        "source_text": "paris-bible/Previous_GroundTruth/LAD2013.051_1r-20r.txt",
        "note": (
            "LAD 1.3 blind eval pages have text GT only in the Paris Bible repo; "
            "no public page images in PBP 1.0. Acquire folio scans separately, "
            "convert to PAGE-XML, then append paths to lad_eval_manifest.txt."
        ),
        "target_cer": "0.03-0.05",
        "reference": "Gueville & Wrisley halshs-03725166 (LAD 1.3 ~3% CER)",
        "manifest_paths": [],
    }
    (gt / "lad_eval.json").write_text(json.dumps(lad_eval, indent=2) + "\n", encoding="utf-8")
    (gt / "lad_eval_manifest.txt").write_text("", encoding="utf-8")
    print("  lad_eval.json + empty lad_eval_manifest.txt (LAD 2013.051 — images TBD)")

    summary = {
        "core_train": len(core_train),
        "core_val": len(core_val),
        "bullinger_train": len(bull_train),
        "bullinger_val": len(bull_val),
        "full_train": len(full_train),
        "full_val": len(full_val),
        "gothic_bible_train": len(gothic_train),
        "gothic_bible_val": len(gothic_val),
        "paris_bible_train": paris_train,
        "paris_bible_val": paris_val,
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
            "r8_gothic_bible": {
                "base": "gm-htr-r5-best",
                "fallback_base": "gm-htr-r2_best",
                "train": "gothic_bible_train_manifest.txt",
                "val": "gothic_bible_val_manifest.txt",
                "blind_eval": "lad_eval_manifest.txt",
                "resize": "union",
                "corpora": sorted(GOTHIC_BIBLE_CORPORA),
                "note": (
                    "Gothic book Latin specialist (Paris Bible PBP 1.0 + CREMMA/HTRomance). "
                    "LAD 2013.051 blind eval when images acquired."
                ),
            },
            "r8_trocr_gothic_bible": {
                "base": "microsoft/trocr-base-handwritten",
                "train": "gothic_bible_train_manifest.txt",
                "val": "gothic_bible_val_manifest.txt",
                "output": "models/trocr-gothic-bible",
                "script": "scripts/train_trocr_htr.py",
                "sbatch": "scripts/r8_trocr_gothic_bible.sbatch",
                "note": "TrOCR line OCR fine-tune on same gothic-bible manifest as Kraken r8.",
            },
        },
    }
    (gt / "retrain_plan.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[split] wrote retrain_plan.json")


if __name__ == "__main__":
    main()
