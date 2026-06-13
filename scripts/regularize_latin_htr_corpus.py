#!/usr/bin/env python3
"""Regularize the medieval Latin HTR corpus for reproducible HPC training.

Fixes problems in the ad-hoc round5 build:
  - Mixed formats (PAGE-XML, HuggingFace PNG+.gt.txt, Bullinger split-zips)
  - Global random train/val shuffle (corpus leakage)
  - Hardcoded /home/seth/src imageFilename paths
  - No per-sample metadata for computational methods / citation

Outputs under --out-dir (default: <corpora-root>/../latin-corpus-gt):
  train_manifest.txt   absolute PAGE-XML paths
  val_manifest.txt
  metadata.jsonl       one record per training line
  corpus_stats.json
  audit.md

Training GT aligns with the CATMuS / CoMMA ecosystem
(https://comma.inria.fr/homepage): human GT corpora (CATMuS, Tridis, CREMMA, …).
CoMMA itself is auto-transcribed browse data — cite for reference/eval, not GT.

Usage:
    python scripts/regularize_latin_htr_corpus.py \\
        --corpora-root /ocean/.../transcriber-shell/src/htr-corpora \\
        --src-root /ocean/.../transcriber-shell/src \\
        --extract-bullinger --workers 8
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from alto_to_pagexml import convert_paris_bible  # noqa: E402
from pagexml_line_strip import (  # noqa: E402
    convert_png_gt_pair,
    find_image_for_xml,
    write_line_strip_pagexml,
)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
SKIP_PARTS = {".git", "chocomufin", "__pycache__"}
TRAIN_PARTS = {"train", "training"}
VAL_PARTS = {"val", "validation", "dev"}
TEST_PARTS = {"test"}
DEFAULT_REGISTRY = _SCRIPT_DIR / "latin_htr_corpus_registry.yaml"
DEFAULT_GT_MSS_REGISTRY = _SCRIPT_DIR / "gt_mss_registry.yaml"


@dataclass
class Sample:
    xml_path: Path
    corpus: str
    split: str
    image_path: Path
    meta: dict = field(default_factory=dict)


def _load_registry(path: Path) -> tuple[dict, set[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    corpora = data.get("corpora") or {}
    exclude = set(data.get("exclude") or [])
    exclude.add("bullinger-htr")
    return corpora, exclude


def _corpus_name(corpora_root: Path, path: Path) -> str:
    try:
        rel = path.relative_to(corpora_root)
        return rel.parts[0] if rel.parts else path.name
    except ValueError:
        return path.name


def _split_from_path(corpora_root: Path, xml_path: Path) -> str | None:
    try:
        parts = {p.lower() for p in xml_path.relative_to(corpora_root).parts}
    except ValueError:
        return None
    if parts & TEST_PARTS:
        return "val"  # upstream test → val for ketos (no separate test in train)
    if parts & VAL_PARTS:
        return "val"
    if parts & TRAIN_PARTS:
        return "train"
    return None


def _should_skip_path(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_PARTS:
        return True
    s = str(path).lower()
    if any(tok in s for tok in ("comma-rerecognition", "comma-jsonl", "comma-other-formats")):
        return True
    name = path.name.lower()
    return "chocomufin" in name


def extract_bullinger(corpora_root: Path, workers: int = 4) -> Path:
    """Extract bullinger split-zips into bullinger-extracted/."""
    bull = corpora_root / "bullinger-htr"
    out = corpora_root / "bullinger-extracted"
    if not bull.is_dir():
        print("[bullinger] no bullinger-htr directory — skip extract")
        return out

    def extract_split(split: str) -> None:
        sdir = bull / split
        dest = out / split
        if not sdir.is_dir():
            return
        dest.mkdir(parents=True, exist_ok=True)
        zips = sorted(sdir.glob("*.zip"))
        if not zips:
            return
        print(f"[bullinger] extracting {len(zips)} archives → {dest}")
        for z in zips:
            if (dest / f".{z.stem}.done").exists():
                continue
            if _have_7z():
                subprocess.run(
                    ["7z", "x", "-y", f"-o{dest}", str(z)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                merged = dest / f"{z.stem}.merged.zip"
                subprocess.run(
                    ["zip", "-q", "-s", "0", str(z), "--out", str(merged)],
                    check=False,
                )
                subprocess.run(
                    ["unzip", "-q", "-o", str(merged), "-d", str(dest)],
                    check=False,
                )
                merged.unlink(missing_ok=True)
            (dest / f".{z.stem}.done").touch()

    for split in ("train", "val", "test"):
        extract_split(split)

    # .txt → .gt.txt (idempotent)
    for txt in out.rglob("*.txt"):
        if txt.name.endswith(".gt.txt"):
            continue
        gt = txt.with_suffix(".gt.txt")
        if not gt.exists():
            gt.write_bytes(txt.read_bytes())

    return out


def _have_7z() -> bool:
    from shutil import which

    return which("7z") is not None


def convert_line_strips(corpus_dir: Path, *, workers: int, overwrite: bool) -> tuple[int, int, int]:
    pairs = [
        p
        for p in corpus_dir.rglob("*.png")
        if not _should_skip_path(p) and p.with_suffix(".gt.txt").is_file()
    ]
    if not pairs:
        return 0, 0, 0

    ok = skip = err = 0
    if workers <= 1:
        for img in pairs:
            r = convert_png_gt_pair(img, overwrite=overwrite)
            if r == "ok":
                ok += 1
            elif r == "skip":
                skip += 1
            else:
                err += 1
        return ok, skip, err

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(convert_png_gt_pair, p, overwrite=overwrite): p for p in pairs}
        for fut in as_completed(futs):
            r = fut.result()
            if r == "ok":
                ok += 1
            elif r == "skip":
                skip += 1
            else:
                err += 1
    return ok, skip, err


def fix_xml_image_path(xml_path: Path, *, path_prefixes: list[tuple[str, str]]) -> bool:
    """Ensure Page/@imageFilename points at an existing absolute image path."""
    import xml.etree.ElementTree as ET

    if not xml_path.is_file():
        return False
    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, OSError):
        return False

    root = tree.getroot()
    ns_m = re.match(r"\{([^}]+)\}", root.tag)
    ns = ns_m.group(1) if ns_m else ""
    page_tag = f"{{{ns}}}Page" if ns else "Page"
    page = root.find(f".//{page_tag}")
    if page is None:
        return False

    raw = (page.get("imageFilename") or "").strip()
    candidates: list[Path] = []
    if raw:
        p = Path(raw)
        candidates.append(p)
        if not p.is_absolute():
            candidates.append((xml_path.parent / p).resolve())
        for old, new in path_prefixes:
            if old in raw:
                candidates.append(Path(raw.replace(old, new)).resolve())

    candidates.append(find_image_for_xml(xml_path))
    image: Path | None = None
    for c in candidates:
        if c is not None and c.is_file():
            image = c.resolve()
            break
    if image is None:
        return False

    current = (page.get("imageFilename") or "").strip()
    target = str(image)
    if current == target:
        return True

    page.set("imageFilename", target)
    try:
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    except OSError:
        return False
    return True


def _resolve_split(split_mode: str, path_split: str | None) -> str:
    if split_mode == "train":
        return "train"
    if split_mode == "val_only":
        return "val"
    if path_split in ("train", "val"):
        return path_split
    if split_mode == "holdout":
        return "holdout_pending"
    return path_split or "holdout_pending"


def scan_corpus(
    corpus_dir: Path,
    corpus: str,
    cfg: dict,
    *,
    split_root: Path,
    path_prefixes: list[tuple[str, str]],
    workers: int,
) -> list[Sample]:
    if not corpus_dir.is_dir():
        return []

    split_mode = (cfg or {}).get("split_mode", "holdout")
    samples: list[Sample] = []

    scan_root = corpus_dir
    sub = (cfg or {}).get("scan_subdir")
    if sub:
        scan_root = corpus_dir / sub
        if not scan_root.is_dir():
            return []

    xmls = sorted(
        x
        for x in scan_root.rglob("*.xml")
        if not _should_skip_path(x) and x.is_file()
    )

    for xml_path in xmls:
        fix_xml_image_path(xml_path, path_prefixes=path_prefixes)

    for xml_path in xmls:
        image = find_image_for_xml(xml_path)
        if image is None:
            continue
        path_split = _split_from_path(split_root, xml_path)
        split = _resolve_split(split_mode, path_split)
        meta = {
            "corpus": corpus,
            "xml": str(xml_path.resolve()),
            "image": str(image),
            "languages": (cfg or {}).get("languages", []),
            "era": (cfg or {}).get("era"),
            "script": (cfg or {}).get("script"),
            "citation": (cfg or {}).get("citation"),
            "url": (cfg or {}).get("url"),
            "comma_ecosystem": corpus == "catmus-medieval",
            "source": (cfg or {}).get("source", "htr-corpora"),
        }
        if meta["source"] == "gt-mss":
            meta["human_gt"] = True
        samples.append(
            Sample(
                xml_path=xml_path.resolve(),
                corpus=corpus,
                split=split,
                image_path=image,
                meta=meta,
            )
        )

    return samples


def _load_gt_mss_registry(path: Path) -> tuple[list[dict], set[str], list[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources") or []
    skip = set(data.get("skip_paths") or [])
    priority = list(data.get("dedupe_priority") or [])
    return sources, skip, priority


def scan_gt_mss(
    gt_root: Path,
    registry_path: Path,
    *,
    path_prefixes: list[tuple[str, str]],
    workers: int,
) -> list[Sample]:
    if not gt_root.is_dir():
        print(f"[gt-mss] root missing (skip): {gt_root}")
        return []

    sources, skip_paths, _ = _load_gt_mss_registry(registry_path)
    all_samples: list[Sample] = []

    for entry in sources:
        rel = entry["path"]
        if rel in skip_paths:
            continue
        corpus_dir = gt_root / rel
        corpus = entry["corpus"]
        cfg = {**entry, "source": "gt-mss"}
        found = scan_corpus(
            corpus_dir,
            corpus,
            cfg,
            split_root=gt_root,
            path_prefixes=path_prefixes,
            workers=workers,
        )
        if found:
            print(f"[gt-mss] {corpus}: {len(found):,} paired XML+image ({rel})")
        all_samples.extend(found)

    return all_samples


def dedupe_samples(samples: list[Sample], priority: list[str]) -> tuple[list[Sample], int]:
    """Drop duplicate page stems; prefer human GT corpora per priority list."""
    prio = {name: i for i, name in enumerate(priority)}
    best: dict[str, Sample] = {}
    for s in samples:
        stem = s.xml_path.stem.lower()
        if stem not in best:
            best[stem] = s
            continue
        cur_rank = prio.get(s.corpus, len(priority) + 1)
        old_rank = prio.get(best[stem].corpus, len(priority) + 1)
        if cur_rank < old_rank:
            best[stem] = s
    removed = len(samples) - len(best)
    return list(best.values()), removed


def assign_holdout_splits(samples: list[Sample], *, seed: int, val_frac: float) -> None:
    by_corpus: dict[str, list[Sample]] = defaultdict(list)
    for s in samples:
        if s.split == "holdout_pending":
            by_corpus[s.corpus].append(s)

    for corpus, group in by_corpus.items():
        rng = random.Random(f"{seed}:{corpus}")
        paths = list(group)
        rng.shuffle(paths)
        n_val = max(1, int(len(paths) * val_frac))
        for i, s in enumerate(paths):
            s.split = "val" if i < n_val else "train"


def build_manifests(
    samples: list[Sample],
    *,
    seed: int,
    val_frac: float,
) -> tuple[list[Sample], list[Sample]]:
    assign_holdout_splits(samples, seed=seed, val_frac=val_frac)

    train = [s for s in samples if s.split == "train"]
    val = [s for s in samples if s.split == "val"]

    rng = random.Random(seed)
    rng.shuffle(train)
    val.sort(key=lambda s: (s.corpus, str(s.xml_path)))
    return train, val


def write_outputs(
    out_dir: Path,
    train: list[Sample],
    val: list[Sample],
    *,
    corpora_root: Path,
    gt_mss_root: Path,
    registry: dict,
    audit_lines: list[str],
    convert_stats: dict[str, tuple[int, int, int]],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "train_manifest.txt").write_text(
        "\n".join(str(s.xml_path) for s in train) + ("\n" if train else ""),
        encoding="utf-8",
    )
    (out_dir / "val_manifest.txt").write_text(
        "\n".join(str(s.xml_path) for s in val) + ("\n" if val else ""),
        encoding="utf-8",
    )

    with (out_dir / "metadata.jsonl").open("w", encoding="utf-8") as fh:
        for s in train + val:
            row = {**s.meta, "split": s.split}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    by_corpus: dict[str, dict[str, int]] = defaultdict(lambda: {"train": 0, "val": 0})
    for s in train:
        by_corpus[s.corpus]["train"] += 1
    for s in val:
        by_corpus[s.corpus]["val"] += 1

    stats = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpora_root": str(corpora_root.resolve()),
        "gt_mss_root": str(gt_mss_root),
        "total_train": len(train),
        "total_val": len(val),
        "per_corpus": dict(sorted(by_corpus.items())),
        "convert_line_strips": convert_stats,
        "comma_reference": "https://comma.inria.fr/homepage",
        "comma_note": (
            "CoMMA is auto-transcribed browse data; this corpus uses human GT "
            "(CATMuS, Tridis, CREMMA, …) for supervised training."
        ),
        "registry_corpora": sorted(registry.keys()),
    }
    (out_dir / "corpus_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    audit = [
        "# Latin HTR corpus audit",
        "",
        f"Generated: {stats['generated_at']}",
        f"Corpora root: `{corpora_root}`",
        "",
        "## Summary",
        f"- Train lines: **{len(train):,}**",
        f"- Val lines: **{len(val):,}**",
        "",
        "## Per-corpus counts",
        "",
        "| Corpus | Train | Val |",
        "|--------|------:|----:|",
    ]
    for name in sorted(by_corpus):
        audit.append(
            f"| {name} | {by_corpus[name]['train']:,} | {by_corpus[name]['val']:,} |"
        )
    audit.extend(["", "## Line-strip → PAGE-XML conversion", ""])
    for name, (ok, skip, err) in sorted(convert_stats.items()):
        audit.append(f"- **{name}**: {ok:,} written, {skip:,} skipped, {err} errors")
    audit.extend(["", "## Notes", ""])
    audit.extend(audit_lines)
    (out_dir / "audit.md").write_text("\n".join(audit) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--corpora-root",
        type=Path,
        default=Path("~/src/htr-corpora").expanduser(),
        help="Root containing corpus subdirectories",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output dir (default: <corpora-root>/../latin-corpus-gt)",
    )
    p.add_argument(
        "--src-root",
        type=Path,
        default=None,
        help="Target absolute src root for path rewrites (e.g. Bridges /ocean/.../src)",
    )
    p.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="Corpus registry YAML",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--val-frac", type=float, default=0.05)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument(
        "--extract-bullinger",
        action="store_true",
        help="Extract bullinger-htr split-zips into bullinger-extracted/",
    )
    p.add_argument(
        "--convert-strips",
        action="store_true",
        default=True,
        help="Convert PNG+.gt.txt line strips to PAGE-XML (default: on)",
    )
    p.add_argument("--no-convert-strips", action="store_false", dest="convert_strips")
    p.add_argument(
        "--overwrite-xml",
        action="store_true",
        help="Regenerate PAGE-XML for line strips even when .xml exists",
    )
    p.add_argument(
        "--min-samples",
        type=int,
        default=10_000,
        help="Abort if fewer than this many train+val samples",
    )
    p.add_argument(
        "--gt-mss-root",
        type=Path,
        default=None,
        help="Human GT mss root (default: <src-root>/../gt-mss)",
    )
    p.add_argument(
        "--gt-mss-registry",
        type=Path,
        default=DEFAULT_GT_MSS_REGISTRY,
        help="GT manuscript registry YAML",
    )
    args = p.parse_args()

    corpora_root = args.corpora_root.expanduser().resolve()
    if not corpora_root.is_dir():
        sys.exit(f"corpora-root not found: {corpora_root}")

    out_dir = (
        args.out_dir.expanduser().resolve()
        if args.out_dir
        else (corpora_root.parent / "latin-corpus-gt").resolve()
    )
    src_root = (args.src_root or corpora_root.parent).expanduser().resolve()
    gt_mss_root = (
        args.gt_mss_root.expanduser().resolve()
        if args.gt_mss_root
        else (src_root.parent / "gt-mss").resolve()
    )

    registry, exclude = _load_registry(args.registry.expanduser().resolve())
    _, _, gt_dedupe_priority = _load_gt_mss_registry(
        args.gt_mss_registry.expanduser().resolve()
    )

    path_prefixes = [
        ("/home/seth/src", str(src_root)),
        ("/home/sethj/disk3", str(src_root)),
        ("/home/sethj/src", str(src_root)),
        ("/home/seth/kraken-vatlib-gt", str(gt_mss_root / "akdeniz/kraken-vatlib-gt")),
        ("/home/seth/kraken-cp40-gt", str(gt_mss_root / "akdeniz/kraken-cp40-gt")),
        ("/home/seth/kraken-done-lines-gt", str(gt_mss_root / "akdeniz/kraken-done-lines-gt")),
        ("/home/seth/deed-finetune-gt", str(gt_mss_root / "akdeniz/deed-finetune-gt")),
        (
            "/Users/halxiii/Library/CloudStorage/Dropbox",
            str(gt_mss_root / "dropbox"),
        ),
    ]

    audit_lines: list[str] = [
        "- Replaced round5 global shuffle with **corpus-aware splits** "
        "(upstream train/val/test dirs, or per-corpus holdout).",
        "- Normalized line strips and **Paris Bible ALTO** to PAGE-XML with absolute `imageFilename`.",
        "- Wrote **metadata.jsonl** for computational methods / provenance.",
        f"- Path prefixes rewritten toward `{src_root}`.",
        "- [CoMMA](https://comma.inria.fr/homepage) cited as browse/reference corpus; "
        "supervised GT is human-transcribed sources (see `scripts/htr_corpora.bib`).",
        f"- Ingested human GT mss from `{gt_mss_root}` (Dropbox + akdeniz kraken dirs).",
    ]

    if args.extract_bullinger:
        extract_bullinger(corpora_root)

    convert_stats: dict[str, tuple[int, int, int]] = {}
    if args.convert_strips:
        for child in sorted(corpora_root.iterdir()):
            if not child.is_dir() or child.name in exclude:
                continue
            if child.name == "bullinger-htr":
                continue
            ok, skip, err = convert_line_strips(
                child, workers=args.workers, overwrite=args.overwrite_xml
            )
            if ok or skip or err:
                convert_stats[child.name] = (ok, skip, err)
                print(f"[convert] {child.name}: {ok:,} ok, {skip:,} skip, {err} err")

    all_samples: list[Sample] = []
    discovered = sorted(
        d.name for d in corpora_root.iterdir() if d.is_dir() and d.name not in exclude
    )

    for corpus in discovered:
        corpus_dir = corpora_root / corpus
        cfg = registry.get(corpus, {})
        cfg = {**cfg, "source": "htr-corpora"}
        if cfg.get("format") == "alto" or corpus == "paris-bible":
            ok, skip, err = convert_paris_bible(
                corpus_dir,
                workers=args.workers,
                overwrite=args.overwrite_xml,
            )
            if ok or skip or err:
                convert_stats[f"{corpus}-alto"] = (ok, skip, err)
                print(f"[alto] {corpus}: {ok:,} ok, {skip:,} skip, {err} err → page-xml/")
        found = scan_corpus(
            corpus_dir,
            corpus,
            cfg,
            split_root=corpora_root,
            path_prefixes=path_prefixes,
            workers=args.workers,
        )
        print(f"[scan] {corpus}: {len(found):,} paired XML+image")
        all_samples.extend(found)

    gt_samples = scan_gt_mss(
        gt_mss_root,
        args.gt_mss_registry.expanduser().resolve(),
        path_prefixes=path_prefixes,
        workers=args.workers,
    )
    all_samples.extend(gt_samples)

    all_samples, deduped = dedupe_samples(all_samples, gt_dedupe_priority)
    if deduped:
        print(f"[dedupe] removed {deduped:,} duplicate page stems (GT priority)")
        audit_lines.append(f"- Deduplicated **{deduped:,}** duplicate stems; human GT wins.")

    if len(all_samples) < args.min_samples:
        sys.exit(
            f"Only {len(all_samples):,} samples (need ≥ {args.min_samples:,}). "
            "Is the corpora root complete?"
        )

    train, val = build_manifests(all_samples, seed=args.seed, val_frac=args.val_frac)
    write_outputs(
        out_dir,
        train,
        val,
        corpora_root=corpora_root,
        gt_mss_root=gt_mss_root,
        registry=registry,
        audit_lines=audit_lines,
        convert_stats=convert_stats,
    )

    print()
    print(f"Wrote {out_dir}/")
    print(f"  train: {len(train):,}  val: {len(val):,}")
    print()
    print("Next: ketos train -f page -t train_manifest.txt -e val_manifest.txt ...")


if __name__ == "__main__":
    main()
