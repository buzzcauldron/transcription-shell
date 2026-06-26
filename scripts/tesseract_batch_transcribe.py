#!/usr/bin/env python3
"""Batch Tesseract transcription → protocol YAML — no LLM, no lineation.

Produces correctable draft transcriptions for print/incunabula pages using
pytesseract directly (bypasses historical-ocr's layout pipeline).  Each output
is a minimal protocol YAML that can be corrected and fed into yaml-to-tei.

Usage:
    python scripts/tesseract_batch_transcribe.py \\
        --images /path/to/pages/*.jpg \\
        --out-dir /path/to/output \\
        --lang lat+frk \\
        --psm 6 \\
        --skip-existing

Reference: Strickland et al. 2026 — Tesseract baseline before LLM correction.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import sys
from pathlib import Path

import yaml


def _tesseract_text(image_path: Path, lang: str, psm: int) -> str:
    try:
        import pytesseract
    except ImportError as e:
        raise SystemExit("pytesseract not installed: pip install pytesseract") from e
    from PIL import Image

    with Image.open(image_path) as img:
        config = f"--psm {psm}"
        return pytesseract.image_to_string(img, lang=lang, config=config)


def _make_yaml(page_id: str, text: str) -> dict:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    return {
        "transcriptionOutput": {
            "protocolVersion": "1.1.0",
            "metadata": {
                "sourcePageId": page_id,
                "modelId": "tesseract",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "targetLanguage": "lat-latn",
                "normalizationMode": "diplomatic",
                "diplomaticProfile": "draft",
                "diplomaticToggles": {
                    "preserveLineBreaks": True,
                    "preserveOriginalAbbreviations": True,
                    "markExpansions": False,
                    "captureDeletionsAndInsertions": False,
                    "captureUnclearGlyphShape": False,
                },
                "runMode": "tesseract_only",
            },
            "preCheck": {
                "resolutionAdequate": True,
                "orientationCorrect": True,
            },
            "segments": [
                {
                    "position": "body",
                    "text": "\n".join(lines),
                    "lineRange": [1, len(lines)],
                }
            ],
        }
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--images", nargs="+", required=True,
                    help="Image paths or glob patterns")
    ap.add_argument("--out-dir", required=True, help="Output directory for YAMLs")
    ap.add_argument("--lang", default="lat+frk",
                    help="Tesseract language(s) (default: lat+frk)")
    ap.add_argument("--psm", type=int, default=6,
                    help="Tesseract page segmentation mode (default: 6)")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Skip pages with an existing YAML")
    args = ap.parse_args()

    images: list[Path] = []
    for pattern in args.images:
        expanded = glob.glob(pattern)
        if expanded:
            images.extend(Path(p) for p in sorted(expanded))
        else:
            images.append(Path(pattern))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ok = err = skipped = 0
    for img in images:
        page_id = img.stem
        out_path = out_dir / f"{page_id}_transcription.yaml"

        if args.skip_existing and out_path.is_file():
            skipped += 1
            continue

        print(f"  {page_id} … ", end="", flush=True)
        try:
            text = _tesseract_text(img, args.lang, args.psm)
            data = _make_yaml(page_id, text)
            out_path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
            line_count = text.count("\n")
            print(f"ok ({line_count} lines)")
            ok += 1
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            err += 1

    print(f"\ndone — ok={ok} skipped={skipped} errors={err}")
    if err:
        sys.exit(1)


if __name__ == "__main__":
    main()
