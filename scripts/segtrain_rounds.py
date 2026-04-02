"""Incremental ketos segtrain across batches of ~100 pages.

Each round fine-tunes from the previous round's output, keeping deed GT
and any --anchor-gt directories in every round. Works on MPS (Apple Silicon),
CUDA, or CPU. Device, batch size, and workers are auto-detected from the
hardware if not overridden.

Usage:
    python segtrain_rounds.py               # fully auto-detected

    # Override paths:
    python segtrain_rounds.py \\
        --vatlib-gt ~/kraken-vatlib-gt \\
        --deed-gt ~/deed-finetune-gt \\
        --base-model ~/model_249.mlmodel \\
        --out ~/kraken-finetuned.mlmodel

    # Add extra anchor GT dirs (included every round, like deed GT):
    python segtrain_rounds.py \\
        --anchor-gt ~/kraken-cp40-gt \\
        --anchor-gt ~/kraken-done-lines-gt \\
        --out ~/kraken-son-of-gm.mlmodel

    # Resume from a specific round (0-indexed); use the last epoch checkpoint, e.g.:
    python segtrain_rounds.py --start-round 2 --resume-model ~/src/kraken-round1.mlmodel_49.mlmodel

    # Override auto-detected hardware settings:
    python segtrain_rounds.py --device cpu --batch-size 4 --workers 2 --epochs 30
"""

from __future__ import annotations

import argparse
import os
import platform
import random
import shutil
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


def _detect_device() -> str:
    """Return the best available ketos device string."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda:0"
        if torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _gpu_vram_mib(device: str) -> int:
    """Return total VRAM in MiB for a CUDA device, 0 otherwise."""
    if not device.startswith("cuda"):
        return 0
    try:
        import torch
        idx = int(device.split(":")[-1]) if ":" in device else 0
        return torch.cuda.get_device_properties(idx).total_memory // (1024 * 1024)
    except Exception:
        return 0


def _suggest_batch_size(device: str) -> int:
    """Vatlib pages per round based on available VRAM/device."""
    if device == "mps":
        return 8
    if device == "cpu":
        return 4
    vram = _gpu_vram_mib(device)
    if vram >= 20_000:   # RTX 4090, A100, etc.
        return 40
    if vram >= 10_000:   # RTX 3080 10 GB, RTX 3080 Ti, etc.
        return 20
    if vram >= 8_000:    # RTX 3070, RTX 2080, etc.
        return 12
    return 6             # low VRAM fallback


def _suggest_anchor_batch_size(device: str) -> int:
    """Anchor pages sampled per round (deed + all anchor-gt dirs combined)."""
    if device == "mps":
        return 8
    if device == "cpu":
        return 4
    vram = _gpu_vram_mib(device)
    if vram >= 20_000:
        return 40
    if vram >= 10_000:
        return 20
    if vram >= 8_000:
        return 12
    return 6


def _suggest_workers(device: str) -> int:
    """DataLoader workers based on CPU count and device."""
    cpus = os.cpu_count() or 2
    if device == "cpu":
        return max(2, min(cpus // 2, 4))
    return max(2, min(cpus // 2, 8))


def _find_ketos() -> str:
    """Locate the ketos binary: PATH first, then common venv locations."""
    found = shutil.which("ketos")
    if found:
        return found
    candidates = [
        Path.home() / ".venv-kraken/bin/ketos",
        Path.home() / ".local/bin/ketos",
        Path(sys.prefix) / "bin/ketos",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "ketos"  # last resort: let subprocess raise a clear error


def main() -> None:
    # Auto-detect hardware defaults before parsing so they show in --help.
    _auto_device = _detect_device()
    _auto_batch = _suggest_batch_size(_auto_device)
    _auto_anchor_batch = _suggest_anchor_batch_size(_auto_device)
    _auto_workers = _suggest_workers(_auto_device)

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vatlib-gt", type=Path, default=_default("~/kraken-vatlib-gt"),
                   help="Directory of vatlib image+XML pairs")
    p.add_argument("--deed-gt", type=Path, default=_default("~/deed-finetune-gt"),
                   help="Directory of deed image+XML pairs (included every round)")
    p.add_argument("--anchor-gt", type=Path, action="append", default=[],
                   metavar="DIR",
                   help="Additional GT directory included in every round (repeatable). "
                        "E.g. --anchor-gt ~/kraken-cp40-gt --anchor-gt ~/kraken-done-lines-gt")
    p.add_argument("--base-model", type=Path, default=_default("~/model_249.mlmodel"),
                   help="Starting model for fine-tuning")
    p.add_argument("--out", type=Path, default=_default("~/src/kraken-finetuned.mlmodel"),
                   help="Final output model path")
    p.add_argument("--device", default=_auto_device,
                   help=f"ketos device string: cpu | mps | cuda:0 (auto-detected: {_auto_device})")
    p.add_argument("--workers", type=int, default=_auto_workers,
                   help=f"DataLoader workers (auto-detected: {_auto_workers})")
    p.add_argument("--batch-size", type=int, default=_auto_batch,
                   help=f"Vatlib pages per round (auto-detected: {_auto_batch})")
    p.add_argument("--anchor-batch-size", type=int, default=_auto_anchor_batch,
                   help=f"Anchor pages sampled per round from deed+anchor-gt combined "
                        f"(auto-detected: {_auto_anchor_batch}; 0 = include all)")
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
    ketos_bin = _find_ketos()

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
    vram_mib = _gpu_vram_mib(args.device)
    vram_str = f" ({vram_mib // 1024} GB VRAM)" if vram_mib else ""
    print(f"Device:       {args.device}{vram_str}")
    print(f"Workers:      {args.workers}")
    print(f"Vatlib XMLs:  {len(vatlib_xmls)}  →  {n_rounds} rounds of ~{args.batch_size}")
    print(f"Deed GT:      {len(deed_xmls)} XMLs included in every round")
    all_anchor_xmls = list(anchor_xmls)  # full pool for per-round sampling
    anchor_sample_n = args.anchor_batch_size if args.anchor_batch_size > 0 else None
    if anchor_xmls:
        sample_desc = f"sampled {anchor_sample_n}/round" if anchor_sample_n else "all"
        print(f"Anchor GT:    {len(anchor_xmls)} XMLs pool ({sample_desc}) from {', '.join(str(d) for d in args.anchor_gt)}")
    print(f"Epochs/round: {args.epochs} (early stopping, min 5)")
    print(f"Base model:   {base_model}")
    print(f"Final output: {final_out}")
    print(f"ketos:        {ketos_bin}")
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

        # Sample anchor pages for this round (deed always included fully; anchor-gt pooled).
        if anchor_sample_n and len(all_anchor_xmls) > anchor_sample_n:
            sampled_anchors = rng.sample(all_anchor_xmls, anchor_sample_n)
        else:
            sampled_anchors = all_anchor_xmls

        total = len(batch) + len(deed_xmls) + len(sampled_anchors)
        print(f"{'='*60}")
        print(f"Round {round_idx + 1}/{n_rounds}  ({len(batch)} vatlib + {len(deed_xmls)} deed + {len(sampled_anchors)} anchor = {total} total)")
        print(f"  input:  {current_model}")
        print(f"  output: {round_out}")
        print(f"{'='*60}")

        xml_args = [str(x) for x in batch] + [str(x) for x in deed_xmls] + [str(x) for x in sampled_anchors]

        cmd = [
            ketos_bin,
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
