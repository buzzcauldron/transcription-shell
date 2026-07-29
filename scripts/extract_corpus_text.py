#!/usr/bin/env python3
"""Extract plain Latin text from transcription YAML artifacts for stylometry.

Prefers ``normalizedLayer`` / expanded text when present so Delta matches
expanded reference corpora. Diplomatic ink forms are for audit, not stylo.

Usage:
    python3 extract_corpus_text.py <job_dir> <out_txt> [--min-words N]
    python3 extract_corpus_text.py <job_dir> <out_txt> --layer diplomatic
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

try:
    import yaml
    _YAML = True
except ImportError:
    _YAML = False


def strip_markup(text: str, *, keep_expansions: bool = True) -> str:
    """Remove protocol markup; optionally keep expansion spellings from [exp:…]."""
    if keep_expansions:
        # [exp:prebenda] → prebenda
        text = re.sub(r"\[exp:([^\]]*)\]", r"\1", text)
    else:
        text = re.sub(r"\[exp:[^\]]*\]", "", text)
    text = re.sub(r"\[unc:[^\]]*\]", "", text)
    text = re.sub(r"\[gap[^\]]*\]", "", text)
    text = re.sub(r"\[fig:[^\]]*\]", "", text)
    text = re.sub(r"\[[^\]]{0,40}\]", "", text)
    text = re.sub(r"<[^>]{0,80}>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def normalise_latin(text: str) -> str:
    """Orthographic normalisation shared with stylometry-r reference sets."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = t.replace("\u00e6", "e").replace("\u0153", "e")
    t = t.replace("ae", "e").replace("oe", "e")
    t = t.replace("j", "i").replace("v", "u")
    # Common diplomatic residues → expanded forms before stripping non-letters.
    t = t.replace("q3", "que").replace("qz", "que")
    t = t.replace("&", " et ").replace("⁊", " et ")
    t = re.sub(r"[^a-z\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _segment_text(seg: dict, layer: str) -> str:
    """Pick diplomatic vs normalized text from a protocol segment."""
    if layer == "normalized":
        for key in ("normalizedLayer", "normalized", "normalized_text", "expanded"):
            val = seg.get(key)
            if isinstance(val, str) and val.strip():
                return val
            if isinstance(val, dict):
                inner = val.get("text") or val.get("transcription") or ""
                if inner:
                    return str(inner)
    return str(seg.get("text") or seg.get("transcription") or "")


def extract_yaml_text(path: Path, *, layer: str = "normalized") -> str:
    raw = path.read_text(encoding="utf-8")
    keep_exp = layer == "normalized"
    if _YAML:
        try:
            data = yaml.safe_load(raw)
            root = data.get("transcriptionOutput") or data if isinstance(data, dict) else {}
            segments = root.get("segments") or []
            lines = []
            for seg in segments:
                if not isinstance(seg, dict):
                    continue
                t = _segment_text(seg, layer)
                if t:
                    lines.append(strip_markup(t, keep_expansions=keep_exp))
            if lines:
                return " ".join(lines)
            return strip_markup(root.get("full_text") or "", keep_expansions=keep_exp)
        except Exception:
            pass
    hits = re.findall(r'^\s+text:\s+"(.*)"', raw, re.MULTILINE)
    return strip_markup(" ".join(h.replace('\\"', '"') for h in hits), keep_expansions=keep_exp)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract Latin text for stylometry (prefer normalized/expanded)."
    )
    ap.add_argument("job_dir", type=Path)
    ap.add_argument("out_txt", type=Path)
    ap.add_argument(
        "--min-words",
        type=int,
        default=200,
        help="Skip pages with fewer words than this (default 200)",
    )
    ap.add_argument(
        "--layer",
        choices=("normalized", "diplomatic"),
        default="normalized",
        help="Text layer for stylo (default: normalized / expanded when present)",
    )
    ap.add_argument(
        "--no-normalise",
        action="store_true",
        help="Skip orthographic Latin normalisation (u/v, j/i, etc.)",
    )
    args = ap.parse_args()

    artifacts = args.job_dir / "03_artifacts_2500"
    if not artifacts.is_dir():
        # Also accept a flat artifacts/<job>/ directory or a single YAML.
        artifacts = args.job_dir
        if not artifacts.is_dir():
            sys.exit(f"not found: {args.job_dir / '03_artifacts_2500'}")

    yamls = sorted(artifacts.rglob("*_transcription.yaml"))
    if not yamls and artifacts.is_file() and artifacts.name.endswith(".yaml"):
        yamls = [artifacts]

    pages = []
    skipped = 0
    for yp in yamls:
        text = extract_yaml_text(yp, layer=args.layer)
        if not args.no_normalise:
            text = normalise_latin(text)
        words = len(text.split())
        if words < args.min_words:
            skipped += 1
            continue
        pages.append(text)

    full_text = "\n\n".join(pages)
    args.out_txt.parent.mkdir(parents=True, exist_ok=True)
    args.out_txt.write_text(full_text, encoding="utf-8")

    total_words = len(full_text.split())
    print(
        f"{args.job_dir.name}: {len(pages)} pages, {skipped} skipped, "
        f"{total_words} words (layer={args.layer}) → {args.out_txt}"
    )


if __name__ == "__main__":
    main()
