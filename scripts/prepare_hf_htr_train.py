"""Download mzzhang2014/glyph_machina from HuggingFace and prepare ground truth for ketos train.

Downloads the dataset, saves paired line images (.png) and ground truth (.gt.txt) files,
then compiles them into Kraken binary (.arrow) training files.

Usage:
    python scripts/prepare_hf_htr_train.py [options]

    # Minimal (saves to ~/src/gm-hf-gt/):
    python scripts/prepare_hf_htr_train.py

    # Override output dir:
    python scripts/prepare_hf_htr_train.py --out ~/src/gm-hf-gt

    # Download only, skip compile (compile separately on the training server):
    python scripts/prepare_hf_htr_train.py --no-compile

    # Use a HuggingFace token (private datasets):
    python scripts/prepare_hf_htr_train.py --hf-token $HF_TOKEN

After running, transfer to CMU and train with htr_train_cmu.sh.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


DATASET_ID = "mzzhang2014/glyph_machina"
DEFAULT_OUT = Path("~/src/gm-hf-gt").expanduser()
DEFAULT_BASE_MODEL = Path("~/src/latin_documents/transfer_learned_1k_lines.mlmodel").expanduser()


def _save_pairs(dataset, out_dir: Path, split: str) -> int:
    """Save (image, text) pairs as PNG + .gt.txt. Returns count saved."""
    split_dir = out_dir / split
    split_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for i, example in enumerate(dataset):
        img = example.get("image")
        text = example.get("text") or example.get("transcription") or example.get("label") or ""
        if img is None or not str(text).strip():
            continue
        stem = f"{split}_{i:06d}"
        img_path = split_dir / f"{stem}.png"
        gt_path = split_dir / f"{stem}.gt.txt"
        img.save(str(img_path))
        gt_path.write_text(str(text).strip(), encoding="utf-8")
        saved += 1
        if saved % 500 == 0:
            print(f"  {split}: {saved} pairs saved…")
    return saved


def _compile_split(split_dir: Path, out_arrow: Path) -> bool:
    """Run ketos compile on a ground truth directory. Returns True on success."""
    png_files = sorted(split_dir.glob("*.png"))
    if not png_files:
        print(f"  No PNG files in {split_dir}, skipping compile.")
        return False
    print(f"  ketos compile: {len(png_files)} images → {out_arrow}")
    result = subprocess.run(["ketos", "compile", "-f", "path", "-o", str(out_arrow)]
                            + [str(p) for p in png_files])
    if result.returncode != 0:
        print(f"  ketos compile failed (exit {result.returncode})")
        return False
    return True


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help=f"Output directory for GT pairs and compiled .arrow files (default: {DEFAULT_OUT})")
    p.add_argument("--base-model", type=Path, default=DEFAULT_BASE_MODEL,
                   help=f"Kraken base model for fine-tuning (default: {DEFAULT_BASE_MODEL})")
    p.add_argument("--splits", nargs="+", default=None,
                   help="Dataset splits to process (default: all available splits)")
    p.add_argument("--no-compile", action="store_true",
                   help="Save pairs only; skip ketos compile (compile on the training server)")
    p.add_argument("--hf-token", default=None,
                   help="HuggingFace token for private datasets")
    p.add_argument("--local-data", type=Path, default=None,
                   help="Directory of already-downloaded parquet files (skips HuggingFace download)")
    args = p.parse_args()

    out_dir = args.out.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from datasets import load_dataset
    except ImportError:
        sys.exit("Install HuggingFace datasets: pip install datasets pillow")

    if args.local_data:
        local_dir = args.local_data.expanduser().resolve()
        train_files = sorted(local_dir.glob("train-*.parquet"))
        test_files = sorted(local_dir.glob("test-*.parquet"))
        data_files = {}
        if train_files:
            data_files["train"] = [str(f) for f in train_files]
        if test_files:
            data_files["test"] = [str(f) for f in test_files]
        print(f"Loading from local parquet files in {local_dir} …")
        ds = load_dataset("parquet", data_files=data_files)
    else:
        print(f"Downloading {DATASET_ID} …")
        ds = load_dataset(DATASET_ID, token=args.hf_token)
    print(f"  Splits available: {list(ds.keys())}")

    splits = args.splits if args.splits else list(ds.keys())
    total = 0
    for split in splits:
        if split not in ds:
            print(f"  Split '{split}' not found, skipping.")
            continue
        print(f"\nSaving split: {split} ({len(ds[split])} examples)")
        n = _save_pairs(ds[split], out_dir, split)
        print(f"  {split}: {n} pairs saved → {out_dir / split}/")
        total += n

    print(f"\nTotal pairs saved: {total} → {out_dir}/")

    if not args.no_compile:
        print("\nCompiling ground truth to Kraken binary format (.arrow) …")
        arrow_files = []
        for split in splits:
            split_dir = out_dir / split
            if not split_dir.is_dir():
                continue
            out_arrow = out_dir / f"{split}.arrow"
            ok = _compile_split(split_dir, out_arrow)
            if ok:
                arrow_files.append(out_arrow)
        if arrow_files:
            print(f"\nCompiled: {[str(a) for a in arrow_files]}")
    else:
        arrow_files = []

    base = args.base_model.expanduser().resolve()
    base_arg = f"-i '{base}'" if base.exists() else "# set -i <base_model>"
    arrow_arg = " \\\n    ".join(f"'{a}'" for a in arrow_files) if arrow_files else f"'{out_dir}/train.arrow' '{out_dir}/validation.arrow'"
    val_arrow = out_dir / "validation.arrow"
    eval_arg = f"--evaluation-files '{val_arrow}'" if val_arrow.exists() else ""

    print(f"""
Next steps
──────────
1. Transfer ground truth to CMU:
   rsync -avz --progress '{out_dir}/' $CMU_HOST:~/src/gm-hf-gt/

   Or run this script directly on CMU (pip install datasets pillow first).

2. On CMU, compile if you used --no-compile:
   ketos compile -o ~/src/gm-hf-gt/train.arrow --workers 4 ~/src/gm-hf-gt/train/*.png

3. Train:
   ketos train \\
     {base_arg} \\
     --resize union \\
     -q early \\
     --min-epochs 10 \\
     -N 150 \\
     --precision bf16-mixed \\
     -d cuda:0 \\
     --workers 4 \\
     {eval_arg} \\
     -o ~/src/gm-hf-htr.mlmodel \\
     {arrow_arg}

   Or use scripts/htr_train_cmu.sh (sets CMU_HOST, syncs, and runs above).

4. Copy result back:
   scp $CMU_HOST:~/src/gm-hf-htr_best.mlmodel ~/src/

5. Point transcriber-shell at the new model:
   TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH=~/src/gm-hf-htr_best.mlmodel
""")


if __name__ == "__main__":
    main()
