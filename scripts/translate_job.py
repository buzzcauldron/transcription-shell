#!/usr/bin/env python3
"""Post-hoc translation for a completed transcription job.

Walks 03_artifacts_2500/ and calls run_translate (DeepL) for each
*_transcription.yaml that does not yet have a sibling *_translation.txt.

Usage:
    python3 scripts/translate_job.py <job_dir> [--provider deepl]

    # e.g.
    python3 scripts/translate_job.py \
        ~/latin-ms-workspace/jobs/pal_lat_1407 \
        --provider deepl
"""
import argparse
import os
import sys
import time
from pathlib import Path

# Load .env from the project root (two levels up from this script's dir)
_env_path = Path(__file__).parents[1] / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import yaml
from transcriber_shell.llm.translate import run_translate, translation_output_path
from transcriber_shell.config import Settings


def extract_text(yaml_data: dict) -> str:
    # new format: segments nested under transcriptionOutput
    root = yaml_data.get("transcriptionOutput") or yaml_data
    segments = root.get("segments") or []
    lines = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = seg.get("text") or seg.get("transcription") or ""
        if text:
            lines.append(text)
    if lines:
        return "\n".join(lines)
    return root.get("full_text") or ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--provider", default="deepl")
    parser.add_argument("--model", default=None)
    parser.add_argument("--artifacts-dir", default="03_artifacts_2500")
    args = parser.parse_args()

    artifacts = args.job_dir / args.artifacts_dir
    if not artifacts.is_dir():
        sys.exit(f"artifacts dir not found: {artifacts}")

    settings = Settings()
    yamls = sorted(artifacts.rglob("*_transcription.yaml"))
    total = len(yamls)
    done = skipped = failed = 0

    print(f"found {total} transcription YAMLs in {artifacts}", flush=True)

    for i, yaml_path in enumerate(yamls, 1):
        out_path = translation_output_path(yaml_path)
        if out_path.exists():
            skipped += 1
            continue

        try:
            data = yaml.safe_load(yaml_path.read_text())
            text = extract_text(data)
        except Exception:
            # YAML is malformed — extract segment text lines with regex
            import re
            raw = yaml_path.read_text(encoding="utf-8")
            lines = re.findall(r'^\s+text:\s+"(.*)"', raw, re.MULTILINE)
            text = "\n".join(l.replace('\\"', '"') for l in lines)
            if text:
                print(f"[{i}/{total}] YAML malformed, regex fallback: {yaml_path.name}", flush=True)
            else:
                print(f"[{i}/{total}] YAML malformed, no text found: {yaml_path.name}", flush=True)
                failed += 1
                continue

        if not text.strip():
            print(f"[{i}/{total}] SKIP (empty) {yaml_path.name}", flush=True)
            skipped += 1
            continue

        try:
            # resolve the source image (01_pages_2500/<stem>.<ext>); None falls
            # back to text-only mode for providers that support it (e.g. Gemini)
            page_stem = yaml_path.parent.name
            img_dir = yaml_path.parents[2] / "01_pages_2500"
            image_path = next(
                (img_dir / f"{page_stem}{ext}" for ext in (".jpg", ".png", ".tif", ".jp2")
                 if (img_dir / f"{page_stem}{ext}").exists()),
                None,
            )
            result = run_translate(
                image_path=image_path,
                diplomatic_text=text,
                provider=args.provider,
                model=args.model,
                settings=settings,
            )
            out_path.write_text(result.text, encoding="utf-8")
            chars = (result.usage or {}).get("characters", len(text))
            print(f"[{i}/{total}] OK {yaml_path.parent.name} ({chars} chars)", flush=True)
            done += 1
        except Exception as e:
            print(f"[{i}/{total}] FAIL {yaml_path.name}: {e}", flush=True)
            failed += 1

        # be polite to the free-tier API
        time.sleep(0.25)

    print(f"\ndone: {done} translated, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
