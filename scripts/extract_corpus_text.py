#!/usr/bin/env python3
"""Extract plain Latin text from transcription YAML artifacts for stylometry.

Walks 03_artifacts_2500/, concatenates all segment text in folio order,
writes a single plain-text file suitable for run_stylo_target.R.

Usage:
    python3 extract_corpus_text.py <job_dir> <out_txt> [--min-words N]
"""
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


def strip_markup(text: str) -> str:
    """Remove transcription protocol markup tags and normalize whitespace."""
    text = re.sub(r'\[unc:[^\]]*\]', '', text)
    text = re.sub(r'\[exp:[^\]]*\]', '', text)
    text = re.sub(r'\[gap[^\]]*\]', '', text)
    text = re.sub(r'\[fig:[^\]]*\]', '', text)
    text = re.sub(r'\[[^\]]{0,40}\]', '', text)
    text = re.sub(r'<[^>]{0,80}>', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def extract_yaml_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    if _YAML:
        try:
            data = yaml.safe_load(raw)
            root = data.get("transcriptionOutput") or data if isinstance(data, dict) else {}
            segments = root.get("segments") or []
            lines = []
            for seg in segments:
                if not isinstance(seg, dict):
                    continue
                t = seg.get("text") or seg.get("transcription") or ""
                if t:
                    lines.append(strip_markup(t))
            if lines:
                return " ".join(lines)
            return strip_markup(root.get("full_text") or "")
        except Exception:
            pass
    # regex fallback for malformed YAML
    hits = re.findall(r'^\s+text:\s+"(.*)"', raw, re.MULTILINE)
    return strip_markup(" ".join(h.replace('\\"', '"') for h in hits))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir", type=Path)
    ap.add_argument("out_txt", type=Path)
    ap.add_argument("--min-words", type=int, default=200,
                    help="Skip pages with fewer words than this (default 200)")
    args = ap.parse_args()

    artifacts = args.job_dir / "03_artifacts_2500"
    if not artifacts.is_dir():
        sys.exit(f"not found: {artifacts}")

    yamls = sorted(artifacts.rglob("*_transcription.yaml"))
    pages = []
    skipped = 0
    for yp in yamls:
        text = extract_yaml_text(yp)
        words = len(text.split())
        if words < args.min_words:
            skipped += 1
            continue
        pages.append(text)

    full_text = "\n\n".join(pages)
    args.out_txt.parent.mkdir(parents=True, exist_ok=True)
    args.out_txt.write_text(full_text, encoding="utf-8")

    total_words = len(full_text.split())
    print(f"{args.job_dir.name}: {len(pages)} pages, {skipped} skipped, "
          f"{total_words} words → {args.out_txt}")


if __name__ == "__main__":
    main()
