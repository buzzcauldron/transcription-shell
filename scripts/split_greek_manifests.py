#!/usr/bin/env python3
"""Split greek-corpus-gt metadata into minuscule vs papyrus training manifests.

Reads metadata.jsonl from regularize_latin_htr_corpus.py --registry greek_htr_….

Usage:
    python scripts/split_greek_manifests.py --gt-dir ~/src/greek-corpus-gt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Byzantine / late book hands (train greek-minuscule specialist)
MINUSCULE_CORPORA = frozenset(
    {
        "eparchos",
        "stavronikita-53",
        "stavronikita-79",
        "stavronikita-114",
        "palatine-anthology-cpgr23",
        "hpgtr",
        "vat-gr-2228-phil-gr-130",
        "ljs380-sextus",
        "eutyches",  # short Greek passages in caroline — keep in minuscule pool
    }
)

# True ancient / documentary papyri (domain-shifted; separate model)
PAPYRUS_CORPORA = frozenset(
    {
        "zenon-papyri",
        "ancient-greek-transcriboquest-2025",
    }
)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gt-dir", type=Path, required=True)
    args = p.parse_args()
    gt = args.gt_dir.expanduser().resolve()
    meta_path = gt / "metadata.jsonl"
    if not meta_path.is_file():
        sys.exit(f"metadata not found: {meta_path}")

    buckets: dict[str, list[str]] = {
        "greek_minuscule_train": [],
        "greek_minuscule_val": [],
        "greek_papyrus_train": [],
        "greek_papyrus_val": [],
        "greek_all_train": [],
        "greek_all_val": [],
    }

    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        xml = row["xml"]
        split = row.get("split", "train")
        corpus = row.get("corpus", "")
        key_split = "train" if split == "train" else "val"

        buckets[f"greek_all_{key_split}"].append(xml)
        if corpus in MINUSCULE_CORPORA:
            buckets[f"greek_minuscule_{key_split}"].append(xml)
        if corpus in PAPYRUS_CORPORA:
            buckets[f"greek_papyrus_{key_split}"].append(xml)

    print(f"[split-greek] writing under {gt}")
    for name, paths in buckets.items():
        out = gt / f"{name}_manifest.txt"
        out.write_text("\n".join(paths) + ("\n" if paths else ""), encoding="utf-8")
        print(f"  {name}_manifest.txt: {len(paths):,}")

    plan = {
        "minuscule_corpora": sorted(MINUSCULE_CORPORA),
        "papyrus_corpora": sorted(PAPYRUS_CORPORA),
        "counts": {k: len(v) for k, v in buckets.items()},
        "notes": (
            "Train gm-htr-greek-minuscule on greek_minuscule_* first (PTA seed). "
            "Optional: fine-tune gm-htr-greek-papyrus from minuscule or PTA on papyrus_*."
        ),
    }
    (gt / "greek_retrain_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[split-greek] plan → {gt / 'greek_retrain_plan.json'}")


if __name__ == "__main__":
    main()
