"""Stratified train/val split for HTR fine-tuning.

ketos's default `--partition 0.9` is a random shuffle, which on a skewed
corpus (e.g. 89% from one manuscript) puts the same dominant source in
both splits. The model learns to do well on that one hand and the
validation metric agrees — neither tells us anything about transfer.

This module groups XML files by a *source key* derived from the filename
prefix and holds out a configurable fraction of each group for validation,
so every source is represented in both train and val proportionally.

Output: a `train_files.txt` and `val_files.txt` ready for
``ketos train -t train.txt -e val.txt``.
"""

from __future__ import annotations

import random
import re
from pathlib import Path


_PREFIX_RE = re.compile(r"^([A-Za-z]+\d*)")


def source_key(stem: str) -> str:
    """Derive a source key from a filename stem.

    ``JUST1-633m5``      → ``JUST1``
    ``CP40.355.AALT.4070`` → ``CP40``
    ``KB27-645m22c``     → ``KB27``
    ``kb27.349.aalt.2908.1`` → ``kb27`` (lowercased prefix counts as its own bucket)
    ``norw1``            → ``norw1``
    ``phillipps_10``     → ``phillipps`` (handles underscore separator)
    """
    # Strip path / extension defensively
    s = stem.replace("_", "-").split("-", 1)[0].split(".", 1)[0]
    m = _PREFIX_RE.match(s)
    if m:
        return m.group(1)
    return s or stem


def stratified_split(
    xml_files: list[Path],
    *,
    val_fraction: float = 0.1,
    min_val_per_source: int = 1,
    seed: int = 0,
) -> tuple[list[Path], list[Path], dict[str, dict]]:
    """Return ``(train, val, stats_by_source)``.

    Within each source group, ``val_fraction`` of files (rounded up to at
    least ``min_val_per_source``) are randomly assigned to val. A source with
    only 1 file goes entirely to train (val needs at least 1 left in train).
    """
    rng = random.Random(seed)
    by_source: dict[str, list[Path]] = {}
    for p in xml_files:
        by_source.setdefault(source_key(p.stem), []).append(p)

    train: list[Path] = []
    val: list[Path] = []
    stats: dict[str, dict] = {}
    for key in sorted(by_source):
        files = sorted(by_source[key])
        rng.shuffle(files)
        if len(files) <= 1:
            train.extend(files)
            stats[key] = {"total": len(files), "train": len(files), "val": 0}
            continue
        n_val_target = max(min_val_per_source, int(round(len(files) * val_fraction)))
        n_val = min(n_val_target, len(files) - 1)
        val.extend(files[:n_val])
        train.extend(files[n_val:])
        stats[key] = {"total": len(files), "train": len(files) - n_val, "val": n_val}

    return sorted(train), sorted(val), stats


def write_split_files(
    src_dir: Path,
    train_txt: Path,
    val_txt: Path,
    *,
    val_fraction: float = 0.1,
    seed: int = 0,
) -> dict:
    """Discover XMLs under src_dir, split, write the two files.

    Each line in the output is an absolute path (ketos expects paths).
    """
    src_dir = Path(src_dir).expanduser().resolve()
    xmls = sorted(src_dir.glob("*.xml"))
    if not xmls:
        raise FileNotFoundError(f"no *.xml under {src_dir}")
    train, val, stats = stratified_split(
        xmls, val_fraction=val_fraction, seed=seed,
    )
    train_txt.parent.mkdir(parents=True, exist_ok=True)
    val_txt.parent.mkdir(parents=True, exist_ok=True)
    train_txt.write_text("\n".join(str(p) for p in train) + "\n", encoding="utf-8")
    val_txt.write_text("\n".join(str(p) for p in val) + "\n", encoding="utf-8")
    return {
        "n_train": len(train),
        "n_val": len(val),
        "by_source": stats,
    }
