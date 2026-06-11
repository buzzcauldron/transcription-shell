#!/usr/bin/env python3
"""Prepare line-image + .gt.txt pairs for tesstrain (pre-1800 print OCR).

Sources:
  - GT4HistOCR line PNGs (*.bin.png / *.nrm.png + matching *.gt.txt)
  - PAGE-XML corpora (crop each TextLine from the page image)

Output layout (tesstrain-compatible flat directory):
  <out-dir>/ground-truth/<unique_id>.png
  <out-dir>/ground-truth/<unique_id>.gt.txt
  <out-dir>/manifest.jsonl
  <out-dir>/stats.json

Usage:
  python scripts/prepare_tesseract_ocr_corpus.py \\
    --corpora-root ~/src/htr-corpora \\
    --out-dir ~/src/tesseract-pre1800-gt \\
    --profile pre1800
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from pagexml_line_strip import find_image_for_xml  # noqa: E402

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
DEFAULT_REGISTRY = _SCRIPT_DIR / "tesseract_ocr_corpus_registry.yaml"
_BOM = "\ufeff"
# Known broken GT4HistOCR asset (tesstrain wiki).
_GT4_SKIP_IMAGES = {
    "dta19/1882-keller_sinngedicht/04970.nrm.png",
    "dta19/1882-keller_sinngedicht/04970.bin.png",
}


@dataclass
class LinePair:
    image_src: Path
    text: str
    corpus: str
    split: str | None = None


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _normalize_text(text: str) -> str:
    text = text.replace(_BOM, "").strip()
    return unicodedata.normalize("NFC", text)


def _safe_id(corpus: str, rel: Path) -> str:
    raw = f"{corpus}__{rel.as_posix().replace('/', '__')}"
    raw = re.sub(r"[^\w.\-]+", "_", raw)
    return raw[:220]


def _gt4_image_for_txt(gt_txt: Path) -> Path | None:
    if not gt_txt.name.endswith(".gt.txt"):
        return None
    base = gt_txt.name[: -len(".gt.txt")]
    for suffix in (".nrm.png", ".bin.png"):
        cand = gt_txt.parent / f"{base}{suffix}"
        if cand.is_file():
            return cand
    return None


def _iter_gt4histocr(corpus_root: Path, corpus_name: str) -> list[LinePair]:
    pairs: list[LinePair] = []
    for gt in sorted(corpus_root.rglob("*.gt.txt")):
        rel = gt.relative_to(corpus_root)
        rel_posix = rel.as_posix()
        if any(rel_posix.endswith(p.split("/", 1)[-1]) for p in _GT4_SKIP_IMAGES if "/" in p):
            continue
        try:
            text = _normalize_text(gt.read_text(encoding="utf-8"))
        except OSError:
            continue
        if not text:
            continue
        img = _gt4_image_for_txt(gt)
        if img is None:
            continue
        skip_key = f"{corpus_root.name}/{rel.parent}/{img.name}"
        if skip_key in _GT4_SKIP_IMAGES:
            continue
        pairs.append(LinePair(image_src=img.resolve(), text=text, corpus=corpus_name))
    return pairs


def _line_text(line: ET.Element) -> str | None:
    for te in line.iter():
        if _strip_ns(te.tag) != "TextEquiv":
            continue
        for child in te:
            if _strip_ns(child.tag) == "Unicode" and child.text:
                t = _normalize_text(child.text)
                if t:
                    return t
    return None


def _parse_points(s: str) -> list[tuple[int, int]]:
    pts: list[tuple[int, int]] = []
    for tok in s.split():
        if "," not in tok:
            continue
        x_s, y_s = tok.split(",", 1)
        try:
            pts.append((int(float(x_s)), int(float(y_s))))
        except ValueError:
            continue
    return pts


def _line_bbox(line: ET.Element) -> tuple[int, int, int, int] | None:
    coords = None
    for child in line:
        if _strip_ns(child.tag) == "Coords":
            coords = child
            break
    if coords is None or not coords.get("points"):
        return None
    pts = _parse_points(coords.get("points", ""))
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _iter_pagexml(corpus_root: Path, corpus_name: str, *, pad_px: int = 6) -> list[LinePair]:
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError("Pillow required: pip install Pillow") from e

    pairs: list[LinePair] = []
    for xml_path in sorted(corpus_root.rglob("*.xml")):
        if "alto" in xml_path.name.lower():
            continue
        img_path = find_image_for_xml(xml_path)
        if img_path is None:
            continue
        try:
            tree = ET.parse(str(xml_path))
        except ET.ParseError:
            continue
        root = tree.getroot()
        try:
            page_im = Image.open(img_path)
            page_im.load()
        except OSError:
            continue
        w, h = page_im.size
        line_idx = 0
        for line in root.iter():
            if _strip_ns(line.tag) != "TextLine":
                continue
            text = _line_text(line)
            if not text:
                continue
            box = _line_bbox(line)
            if box is None:
                continue
            x0, y0, x1, y1 = box
            x0p = max(0, x0 - pad_px)
            y0p = max(0, y0 - pad_px)
            x1p = min(w, x1 + pad_px)
            y1p = min(h, y1 + pad_px)
            if x1p <= x0p or y1p <= y0p:
                continue
            crop = page_im.crop((x0p, y0p, x1p, y1p))
            rel = xml_path.relative_to(corpus_root)
            line_rel = rel.with_suffix(f".l{line_idx:03d}.png")
            line_idx += 1
            pair = LinePair(
                image_src=img_path,
                text=text,
                corpus=corpus_name,
                split=str(line_rel),
            )
            pair.__dict__["_crop_image"] = crop  # type: ignore[attr-defined]
            pairs.append(pair)
    return pairs


def _load_registry(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _resolve_corpora(
    registry: dict,
    *,
    profile: str | None,
    names: list[str] | None,
) -> list[tuple[str, dict]]:
    corpora: dict = registry.get("corpora") or {}
    if names:
        keys = names
    elif profile == "pre1800":
        keys = list(registry.get("pre1800_default") or [])
    else:
        keys = list(corpora.keys())
    out: list[tuple[str, dict]] = []
    for key in keys:
        spec = corpora.get(key)
        if not spec:
            print(f"[warn] unknown corpus {key!r} — skip", file=sys.stderr)
            continue
        out.append((key, spec))
    return out


def _write_pairs(
    pairs: list[LinePair],
    *,
    out_dir: Path,
    link_images: bool,
    max_lines: int | None,
) -> tuple[int, int]:
    gt_dir = out_dir / "ground-truth"
    gt_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.jsonl"
    written = 0
    skipped = 0

    with manifest_path.open("w", encoding="utf-8") as mf:
        for i, pair in enumerate(pairs):
            if max_lines is not None and written >= max_lines:
                break
            rel = Path(pair.split or f"line_{i:06d}.png")
            uid = _safe_id(pair.corpus, rel)
            png_out = gt_dir / f"{uid}.png"
            txt_out = gt_dir / f"{uid}.gt.txt"

            crop = pair.__dict__.get("_crop_image")
            try:
                if crop is not None:
                    crop.save(png_out, format="PNG")
                elif link_images:
                    if png_out.exists():
                        png_out.unlink()
                    png_out.symlink_to(pair.image_src)
                else:
                    from PIL import Image

                    Image.open(pair.image_src).save(png_out, format="PNG")
                txt_out.write_text(pair.text + "\n", encoding="utf-8")
            except OSError:
                skipped += 1
                continue

            mf.write(
                json.dumps(
                    {
                        "id": uid,
                        "corpus": pair.corpus,
                        "image_src": str(pair.image_src),
                        "png": str(png_out),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            written += 1
    return written, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--corpora-root",
        type=Path,
        default=Path(os.environ.get("HTR_CORPORA_ROOT", "~/src/htr-corpora")).expanduser(),
    )
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    ap.add_argument(
        "--profile",
        choices=("pre1800", "all"),
        default="pre1800",
        help="pre1800 = registry pre1800_default bundle (default)",
    )
    ap.add_argument("--corpus", action="append", dest="corpora", help="Repeatable corpus id override")
    ap.add_argument("--max-lines", type=int, default=None, help="Cap lines (smoke tests)")
    ap.add_argument(
        "--symlink",
        action="store_true",
        help="Symlink GT4HistOCR PNGs instead of copying (saves disk)",
    )
    args = ap.parse_args()

    registry = _load_registry(args.registry)
    selected = _resolve_corpora(registry, profile=args.profile, names=args.corpora)
    if not selected:
        print("error: no corpora selected", file=sys.stderr)
        return 1

    all_pairs: list[LinePair] = []
    per_corpus: dict[str, int] = {}

    for name, spec in selected:
        rel_path = spec.get("path", name)
        corpus_dir = (args.corpora_root / rel_path).resolve()
        if not corpus_dir.is_dir():
            print(f"[skip] {name}: missing {corpus_dir}", file=sys.stderr)
            continue
        fmt = spec.get("format", "pagexml")
        if fmt == "gt4histocr":
            pairs = _iter_gt4histocr(corpus_dir, name)
        else:
            pairs = _iter_pagexml(corpus_dir, name)
        per_corpus[name] = len(pairs)
        all_pairs.extend(pairs)
        print(f"[{name}] {len(pairs)} line pairs from {corpus_dir}")

    if not all_pairs:
        print("error: no training lines collected", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    written, skipped = _write_pairs(
        all_pairs,
        out_dir=args.out_dir,
        link_images=args.symlink,
        max_lines=args.max_lines,
    )
    stats = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile": args.profile,
        "corpora_root": str(args.corpora_root),
        "out_dir": str(args.out_dir),
        "per_corpus": per_corpus,
        "lines_collected": len(all_pairs),
        "lines_written": written,
        "lines_skipped": skipped,
    }
    (args.out_dir / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {written} line pairs under {args.out_dir / 'ground-truth'}")
    if skipped:
        print(f"Skipped {skipped} lines (I/O errors)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
