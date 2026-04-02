"""Incremental ketos segtrain across batches of ~100 pages.

Each round fine-tunes from the previous round's output, keeping deed GT
and any --anchor-gt directories in every round. Works on MPS (Apple Silicon),
CUDA, or CPU.

Usage:
    python segtrain_rounds.py --device cuda:0

    # Override paths:
    python segtrain_rounds.py \\
        --vatlib-gt ~/kraken-vatlib-gt \\
        --deed-gt ~/deed-finetune-gt \\
        --base-model ~/model_249.mlmodel \\
        --out ~/kraken-finetuned.mlmodel \\
        --device cuda:0

    # Add extra anchor GT dirs (included every round, like deed GT):
    python segtrain_rounds.py \\
        --anchor-gt ~/kraken-cp40-gt \\
        --anchor-gt ~/kraken-done-lines-gt \\
        --out ~/kraken-son-of-gm.mlmodel \\
        --device cuda:0

    # Resume from a specific round (0-indexed); use the last epoch checkpoint, e.g.:
    python segtrain_rounds.py --start-round 2 --resume-model ~/src/kraken-round1.mlmodel_49.mlmodel

    # Override batch size / epochs:
    python segtrain_rounds.py --batch-size 80 --epochs 30
"""

from __future__ import annotations

import argparse
import platform
import random
import subprocess
import sys
from pathlib import Path

# Patch Lightning's MPS detection on macOS (platform.processor() returns i386
# under some conda envs even on Apple Silicon arm64).
if platform.system() == "Darwin" and platform.machine() == "arm64":
    platform.processor = lambda: "arm64"

SEED = 42


def _default(p: str) -> Path:
    return Path(p).expanduser()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vatlib-gt", type=Path, default=_default("~/src/kraken-vatlib-gt"),
                   help="Directory of vatlib image+XML pairs")
    p.add_argument("--deed-gt", type=Path, default=_default("~/src/deed-finetune-gt"),
                   help="Directory of deed image+XML pairs (included every round)")
    p.add_argument("--anchor-gt", type=Path, action="append", default=[],
                   metavar="DIR",
                   help="Additional GT directory included in every round (repeatable). "
                        "E.g. --anchor-gt ~/kraken-cp40-gt --anchor-gt ~/kraken-done-lines-gt")
    p.add_argument("--base-model", type=Path, default=_default("~/src/latin_documents/model_249.mlmodel"),
                   help="Starting model for fine-tuning")
    p.add_argument("--out", type=Path, default=_default("~/src/kraken-finetuned.mlmodel"),
                   help="Final output model path")
    p.add_argument("--device", default="cuda:0",
                   help="ketos device string: cpu | mps | cuda:0 (default: cuda:0)")
    p.add_argument("--workers", type=int, default=4,
                   help="DataLoader workers (default 4)")
    p.add_argument("--batch-size", type=int, default=100,
                   help="Vatlib pages per round (default 100)")
    p.add_argument("--epochs", type=int, default=50,
                   help="Max epochs per round (default 50)")
    p.add_argument("--start-round", type=int, default=0,
                   help="Resume from this round index (0-based)")
    p.add_argument("--resume-model", type=Path, default=None,
                   help="Model to start from when --start-round > 0")
    args = p.parse_args()

    vatlib_gt = args.vatlib_gt.expanduser().resolve()
    deed_gt = args.deed_gt.expanduser().resolve()
    base_model = args.base_model.expanduser().resolve()
    final_out = args.out.expanduser().resolve()

    vatlib_xmls = sorted(vatlib_gt.glob("*.xml"))
    deed_xmls = sorted(deed_gt.glob("*.xml"))

    anchor_xmls: list[Path] = []
    for anchor_dir in args.anchor_gt:
        d = anchor_dir.expanduser().resolve()
        found = sorted(d.glob("*.xml"))
        if not found:
            print(f"Warning: no XMLs found in anchor-gt dir {d}", file=sys.stderr)
        else:
            anchor_xmls.extend(found)

    if not vatlib_xmls:
        sys.exit(f"No XMLs found in {vatlib_gt}")
    if not base_model.exists():
        sys.exit(f"Base model not found: {base_model}")

    rng = random.Random(SEED)
    shuffled = vatlib_xmls[:]
    rng.shuffle(shuffled)

    batches: list[list[Path]] = []
    for i in range(0, len(shuffled), args.batch_size):
        batches.append(shuffled[i : i + args.batch_size])

    n_rounds = len(batches)
    print(f"Vatlib XMLs:  {len(vatlib_xmls)}  →  {n_rounds} rounds of ~{args.batch_size}")
    print(f"Deed GT:      {len(deed_xmls)} XMLs included in every round")
    if anchor_xmls:
        print(f"Anchor GT:    {len(anchor_xmls)} XMLs included in every round ({', '.join(str(d) for d in args.anchor_gt)})")
    print(f"Device:       {args.device}")
    print(f"Epochs/round: {args.epochs} (early stopping, min 5)")
    print(f"Base model:   {base_model}")
    print(f"Final output: {final_out}")
    print()

    current_model = base_model

    if args.start_round > 0:
        if args.resume_model is None:
            sys.exit("--resume-model is required when --start-round > 0")
        current_model = args.resume_model.expanduser().resolve()
        print(f"Resuming from round {args.start_round}, model: {current_model}\n")

    for round_idx in range(args.start_round, n_rounds):
        batch = batches[round_idx]
        is_last = round_idx == n_rounds - 1
        round_out = final_out if is_last else final_out.parent / f"kraken-round{round_idx}.mlmodel"

        print(f"{'='*60}")
        extra_count = len(deed_xmls) + len(anchor_xmls)
        print(f"Round {round_idx + 1}/{n_rounds}  ({len(batch)} vatlib + {extra_count} anchor pages)")
        print(f"  input:  {current_model}")
        print(f"  output: {round_out}")
        print(f"{'='*60}")

        xml_args = [str(x) for x in batch] + [str(x) for x in deed_xmls] + [str(x) for x in anchor_xmls]

        cmd = [
            sys.executable, __file__,  # re-invoke self? No — invoke ketos directly
        ]
        # Build ketos command directly
        cmd = [
            "/home/seth/.venv-kraken/bin/ketos",
            "-d", args.device,
            "--workers", str(args.workers),
            "segtrain",
            "-i", str(current_model),
            "--resize", "add",
            "-N", str(args.epochs),
            "-o", str(round_out),
        ] + xml_args

        print(f"  ketos -d {args.device} segtrain -i {current_model.name} ... ({len(xml_args)} XMLs)")
        print()

        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"\nRound {round_idx + 1} failed (exit {result.returncode}). Stopping.")
            print(f"\nResume with:")
            print(f"  python segtrain_rounds.py \\")
            print(f"    --start-round {round_idx} \\")
            print(f"    --resume-model {current_model} \\")
            print(f"    --device {args.device}")
            sys.exit(result.returncode)

        # ketos saves epoch checkpoints as <out>_N.mlmodel, not the bare <out> path.
        # Find the last epoch checkpoint to use as input for the next round.
        checkpoints = sorted(
            round_out.parent.glob(f"{round_out.name}_[0-9]*.mlmodel"),
            key=lambda p: int(p.stem.rsplit("_", 1)[-1]),
        )
        best = Path(str(round_out) + "_best.mlmodel")
        if checkpoints:
            current_model = checkpoints[-1]
        elif best.exists():
            current_model = best
        else:
            current_model = round_out  # fallback: ketos may have written bare path in future versions
        print(f"\nRound {round_idx + 1} done → {current_model}\n")

    print(f"\nAll {n_rounds} rounds complete.")
    print(f"Final model: {final_out}")
    print(f"\nAdd to .env:")
    print(f"  TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH={final_out}")
    print(f"  TRANSCRIBER_SHELL_LINEATION_BACKEND=kraken")


if __name__ == "__main__":
    main()
