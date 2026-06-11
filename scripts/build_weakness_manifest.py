#!/usr/bin/env python3
"""Build ketos train/val manifests from latin-corpus-gt/metadata.jsonl filters.

Used by blind-test-driven fine-tunes (see blind_test_training_plan.py).

Usage:
  python scripts/build_weakness_manifest.py --case BM-KB27
  python scripts/build_weakness_manifest.py --filter-script anglicana --filter-corpus gt-dropbox-done-lines
  python scripts/build_weakness_manifest.py --case BM-KB27 --metadata /path/to/metadata.jsonl --out-dir /path/to/out
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = REPO / "scripts" / "blind_test_targets.yaml"


def load_targets(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def build_manifests(
    *,
    metadata_path: Path,
    out_dir: Path,
    prefix: str,
    script: str | None = None,
    corpora: list[str] | None = None,
    exclude_corpora: list[str] | None = None,
    val_corpora: list[str] | None = None,
) -> tuple[int, int]:
    if not metadata_path.is_file():
        raise FileNotFoundError(f"metadata.jsonl not found: {metadata_path}")

    train: list[str] = []
    val: list[str] = []
    val_set = set(val_corpora or [])

    for line in metadata_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        corpus = row.get("corpus", "")
        if script and row.get("script") != script:
            continue
        if corpora and corpus not in corpora:
            continue
        if exclude_corpora and corpus in exclude_corpora:
            continue
        xml = row.get("xml")
        if not xml:
            continue
        split = row.get("split", "train")
        if corpus in val_set or split == "val":
            val.append(xml)
        elif split == "train":
            train.append(xml)

    out_dir.mkdir(parents=True, exist_ok=True)
    train_path = out_dir / f"{prefix}_train_manifest.txt"
    val_path = out_dir / f"{prefix}_val_manifest.txt"
    train_path.write_text("\n".join(train) + ("\n" if train else ""), encoding="utf-8")
    val_path.write_text("\n".join(val) + ("\n" if val else ""), encoding="utf-8")
    return len(train), len(val)


def main() -> int:
    ap = argparse.ArgumentParser(description="Filter metadata.jsonl into ketos manifests")
    ap.add_argument("--case", help="Benchmark case id from blind_test_targets.yaml")
    ap.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    ap.add_argument("--metadata", type=Path, default=None, help="metadata.jsonl (default: GT_ROOT/metadata.jsonl)")
    ap.add_argument("--gt-root", type=Path, default=None, help="latin-corpus-gt directory")
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--prefix", default=None, help="Manifest filename prefix (default: case slug)")
    ap.add_argument("--filter-script", default=None)
    ap.add_argument("--filter-corpus", action="append", default=None)
    ap.add_argument("--val-corpus", action="append", default=None)
    args = ap.parse_args()

    script = args.filter_script
    corpora = args.filter_corpus
    val_corpora = args.val_corpus
    prefix = args.prefix

    if args.case:
        targets = load_targets(args.targets)
        cfg = (targets.get("cases") or {}).get(args.case)
        if not cfg:
            print(f"Unknown case: {args.case}", file=sys.stderr)
            return 1
        mf = cfg.get("metadata_filter") or {}
        script = script or mf.get("script")
        corpora = corpora or cfg.get("train_corpora")
        val_corpora = val_corpora or cfg.get("val_corpora")
        prefix = prefix or args.case.lower().replace("-", "_")

    if not prefix:
        prefix = "weakness"

    gt_root = args.gt_root or Path(
        __import__("os").environ.get("LATIN_CORPUS_GT", REPO / "latin-corpus-gt")
    )
    metadata = args.metadata or (gt_root / "metadata.jsonl")
    out_dir = args.out_dir or gt_root

    try:
        n_train, n_val = build_manifests(
            metadata_path=metadata,
            out_dir=out_dir,
            prefix=prefix,
            script=script,
            corpora=corpora,
            val_corpora=val_corpora,
        )
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    print(f"[manifest] prefix={prefix} train={n_train} val={n_val}")
    print(f"  {out_dir / f'{prefix}_train_manifest.txt'}")
    print(f"  {out_dir / f'{prefix}_val_manifest.txt'}")
    if n_train < 50:
        print("[warn] fewer than 50 training lines — check GT rsync / filters", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
