#!/usr/bin/env python3
"""Filter Institutional Books 1.0 metadata and optionally export OCR text for LLM training.

Paper: https://huggingface.co/papers/2506.08300
Metadata (open): institutional/institutional-books-1.0-metadata
Full text (gated): institutional/institutional-books-1.0

Page images are on **Internet Archive** (not HF). For tesstrain-ready corpora use:
  ./scripts/train_institutional_books_ia.sh
This script only builds metadata manifests; see docs/institutional-books-training.md.

Outputs under --out-dir:
  manifest.jsonl     filtered volume records (always)
  stats.json         filter counts
  texts/<barcode>.txt   per-volume post-processed OCR (--export-text)
  corpus.jsonl       one JSON object per line for LLM fine-tune (--export-text)

Usage:
  # Metadata manifest only (no HF auth):
  python scripts/prepare_institutional_books_corpus.py \\
    --out-dir ~/src/institutional-books-pre1800-lat

  # Export OCR text (requires HF_TOKEN + accepted dataset license):
  HF_TOKEN=... python scripts/prepare_institutional_books_corpus.py \\
    --out-dir ~/src/institutional-books-pre1800-lat --export-text

  python scripts/prepare_institutional_books_corpus.py --profile pre1800_law_latin_llm ...
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REGISTRY = _SCRIPT_DIR / "institutional_books_registry.yaml"
METADATA_REPO = "institutional/institutional-books-1.0-metadata"
FULL_REPO = "institutional/institutional-books-1.0"

_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_CENTURY_UU_RE = re.compile(r"(?<!\d)(\d{2})uu(?!\d)", re.I)


def _load_registry(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid registry: {path}")
    return data


def _parse_years(date1: str | None, date2: str | None) -> tuple[int | None, int | None]:
    """Best-effort MARC publication year range."""
    chunks = [c for c in (date1, date2) if c]
    years: list[int] = []
    for chunk in chunks:
        for m in _CENTURY_UU_RE.finditer(chunk):
            century = int(m.group(1))
            years.extend(range(century * 100, century * 100 + 100))
        for m in _YEAR_RE.finditer(chunk):
            y = int(m.group(1))
            if 1000 <= y <= 2100:
                years.append(y)
    if not years:
        return None, None
    return min(years), max(years)


def _row_languages(row: dict[str, Any]) -> set[str]:
    langs: set[str] = set()
    for key in ("language_src", "language_gen"):
        val = (row.get(key) or "").strip().lower()
        if val:
            langs.add(val)
    dist = row.get("language_distribution_gen") or {}
    for code in dist.get("language") or []:
        if code:
            langs.add(str(code).strip().lower())
    return langs


def _row_ocr_score(row: dict[str, Any]) -> int:
    for key in ("ocr_score_gen", "ocr_score_src"):
        val = row.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
    return 0


def _row_tokens(row: dict[str, Any]) -> int:
    val = row.get("token_count_o200k_base_gen")
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def _matches_profile(row: dict[str, Any], spec: dict[str, Any]) -> tuple[bool, str]:
    langs_wanted = {str(x).lower() for x in spec.get("languages") or []}
    row_langs = _row_languages(row)
    if langs_wanted and not (row_langs & langs_wanted):
        return False, "language"

    year_start, year_end = _parse_years(row.get("date1_src"), row.get("date2_src"))
    cutoff = spec.get("year_end_before")
    if cutoff is not None:
        if year_end is None and year_start is None:
            return False, "date_missing"
        effective_end = year_end if year_end is not None else year_start
        if effective_end is None or effective_end >= int(cutoff):
            return False, "date"

    min_ocr = int(spec.get("min_ocr_score") or 0)
    if _row_ocr_score(row) < min_ocr:
        return False, "ocr"

    min_tokens = int(spec.get("min_tokens") or 0)
    if _row_tokens(row) < min_tokens:
        return False, "tokens"

    topics_wanted = [str(t).upper() for t in (spec.get("topics") or [])]
    if topics_wanted:
        topic = (row.get("topic_or_subject_gen") or "").strip().upper()
        if topic not in topics_wanted:
            return False, "topic"

    return True, "ok"


def _manifest_record(row: dict[str, Any], profile: str) -> dict[str, Any]:
    year_start, year_end = _parse_years(row.get("date1_src"), row.get("date2_src"))
    ht = row.get("hathitrust_data_ext") or {}
    return {
        "barcode": row.get("barcode_src"),
        "profile": profile,
        "title": row.get("title_src"),
        "author": row.get("author_src"),
        "date1_src": row.get("date1_src"),
        "date2_src": row.get("date2_src"),
        "year_start": year_start,
        "year_end": year_end,
        "language_src": row.get("language_src"),
        "language_gen": row.get("language_gen"),
        "languages_detected": sorted(_row_languages(row)),
        "topic_or_subject_gen": row.get("topic_or_subject_gen"),
        "ocr_score_src": row.get("ocr_score_src"),
        "ocr_score_gen": row.get("ocr_score_gen"),
        "token_count_o200k_base_gen": _row_tokens(row),
        "page_count_src": row.get("page_count_src"),
        "hathitrust_url": ht.get("url"),
        "source": METADATA_REPO,
    }


def _iter_metadata() -> Any:
    from datasets import load_dataset

    return load_dataset(METADATA_REPO, split="train", streaming=True)


def _filter_metadata(profile: str, spec: dict[str, Any], max_volumes: int | None) -> list[dict[str, Any]]:
    cap = max_volumes if max_volumes is not None else spec.get("max_volumes")
    selected: list[dict[str, Any]] = []
    reject_counts: dict[str, int] = {}
    scanned = 0

    for row in _iter_metadata():
        scanned += 1
        ok, reason = _matches_profile(row, spec)
        if not ok:
            reject_counts[reason] = reject_counts.get(reason, 0) + 1
            continue
        selected.append(_manifest_record(row, profile))
        if cap and len(selected) >= int(cap):
            break
        if scanned % 100_000 == 0:
            print(f"[filter] scanned={scanned:,} selected={len(selected):,}", file=sys.stderr)

    print(f"[filter] done scanned={scanned:,} selected={len(selected):,}", file=sys.stderr)
    if reject_counts:
        top = sorted(reject_counts.items(), key=lambda kv: -kv[1])[:8]
        print(f"[filter] reject reasons: {top}", file=sys.stderr)
    return selected


def _pages_to_text(pages: Any) -> str:
    if not isinstance(pages, list):
        return ""
    chunks = [str(p).strip() for p in pages if p and str(p).strip()]
    return "\n\n".join(chunks)


def _pick_text(row: dict[str, Any], prefer: str) -> tuple[str, str]:
    """Return (body, field_used). Latin volumes only ship source OCR (text_by_page_src)."""
    if prefer == "postprocessed":
        body = _pages_to_text(row.get("text_by_page_gen"))
        if body:
            return body, "text_by_page_gen"
    body = _pages_to_text(row.get("text_by_page_src"))
    if body:
        return body, "text_by_page_src"
    return "", ""


def _export_texts(
    manifest: list[dict[str, Any]],
    out_dir: Path,
    *,
    prefer: str,
    barcode_field: str = "barcode",
) -> tuple[int, int]:
    from datasets import load_dataset

    wanted = {str(r[barcode_field]) for r in manifest if r.get(barcode_field)}
    if not wanted:
        return 0, 0

    texts_dir = out_dir / "texts"
    texts_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = out_dir / "corpus.jsonl"

    found = 0
    exported = 0
    with corpus_path.open("w", encoding="utf-8") as corpus_f:
        ds = load_dataset(FULL_REPO, split="train", streaming=True)
        for row in ds:
            barcode = str(row.get("barcode_src") or row.get("barcode") or "")
            if barcode not in wanted:
                continue
            found += 1
            body, field_used = _pick_text(row, prefer=prefer)
            if not body:
                continue
            txt_path = texts_dir / f"{barcode}.txt"
            txt_path.write_text(body + "\n", encoding="utf-8")
            meta = next(m for m in manifest if str(m[barcode_field]) == barcode)
            record = {
                **meta,
                "text_path": str(txt_path.relative_to(out_dir)),
                "char_count": len(body),
                "text_field": field_used,
            }
            corpus_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            exported += 1
            if found >= len(wanted):
                break
            if exported % 50 == 0:
                print(f"[export] {exported}/{len(wanted)} volumes", file=sys.stderr)

    print(f"[export] matched={found} exported={exported} missing={len(wanted) - exported}", file=sys.stderr)
    return found, exported


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    ap.add_argument(
        "--profile",
        default=None,
        help="Registry profile (default: registry default_profile)",
    )
    ap.add_argument("--max-volumes", type=int, default=None, help="Cap selected volumes")
    ap.add_argument(
        "--export-text",
        action="store_true",
        help=f"Stream {FULL_REPO} and write per-volume .txt + corpus.jsonl (gated; needs HF_TOKEN)",
    )
    ap.add_argument(
        "--export-text-only",
        action="store_true",
        help="Skip metadata scan; read --out-dir/manifest.jsonl and export OCR text only",
    )
    ap.add_argument(
        "--text-preference",
        choices=("postprocessed", "source"),
        default="postprocessed",
        help="Prefer post-processed OCR text when exporting",
    )
    args = ap.parse_args()

    registry = _load_registry(args.registry)
    profile = args.profile or registry.get("default_profile")
    profiles = registry.get("profiles") or {}
    if profile not in profiles and not args.export_text_only:
        print(f"error: unknown profile {profile!r}", file=sys.stderr)
        return 1
    spec = profiles.get(profile) or {}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out_dir / "manifest.jsonl"

    if args.export_text_only:
        if not manifest_path.is_file():
            print(f"error: --export-text-only needs {manifest_path}", file=sys.stderr)
            return 1
        manifest = [
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not manifest:
            print("error: manifest.jsonl is empty", file=sys.stderr)
            return 1
        profile = manifest[0].get("profile") or profile
        print(f"[manifest] loaded {len(manifest)} volumes from {manifest_path}", file=sys.stderr)
    else:
        manifest = _filter_metadata(profile, spec, args.max_volumes)
        if not manifest:
            print("error: no volumes matched filter", file=sys.stderr)
            return 1
        with manifest_path.open("w", encoding="utf-8") as f:
            for rec in manifest:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    stats = {
        "profile": profile,
        "description": spec.get("description", ""),
        "selected_volumes": len(manifest),
        "total_tokens_o200k_base": sum(int(r.get("token_count_o200k_base_gen") or 0) for r in manifest),
        "metadata_repo": METADATA_REPO,
        "full_repo": FULL_REPO,
        "citation": registry.get("citation"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "export_text": bool(args.export_text or args.export_text_only),
        "export_text_only": bool(args.export_text_only),
    }

    if args.export_text or args.export_text_only:
        if not os.environ.get("HF_TOKEN") and not os.environ.get("HUGGING_FACE_HUB_TOKEN"):
            print(
                "error: --export-text requires HF_TOKEN (accept gated license at "
                f"https://huggingface.co/datasets/{FULL_REPO} first)",
                file=sys.stderr,
            )
            return 1
        found, exported = _export_texts(
            manifest,
            args.out_dir,
            prefer=args.text_preference,
        )
        stats["text_export"] = {"matched": found, "exported": exported}
        if exported == 0:
            print("error: no OCR text exported (check HF access / dataset schema)", file=sys.stderr)
            return 1

    stats_path = args.out_dir / "stats.json"
    stats_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

    print(f"[done] manifest={manifest_path} volumes={len(manifest)}")
    print(f"[done] stats={stats_path}")
    if args.export_text or args.export_text_only:
        print(f"[done] corpus={args.out_dir / 'corpus.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
