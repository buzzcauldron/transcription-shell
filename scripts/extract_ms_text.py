#!/usr/bin/env python3
"""Extract Latin transcription text from a job's 03_artifacts_2500 directory.

Reads all *_transcription.yaml files, concatenates segment text fields,
and writes a single plain-text file suitable for stylo input.

Usage:
    python3 extract_ms_text.py <artifacts_dir> <output_txt>
"""
import sys
import yaml
import re
from pathlib import Path


def clean(text: str) -> str:
    # Expand common medieval abbreviation markers to spaces
    text = re.sub(r'[̴̵̶̷̸̧̨̡̢̣̤̥̦̩̪̫̬̭̮̯̰̱̲̳̃̄̈̊]+', '', text)
    # Normalize Unicode
    import unicodedata
    text = unicodedata.normalize('NFKC', text)
    # Keep only Latin printable + newlines + spaces; drop control chars
    text = re.sub(r'[^\x09\x0a\x0d\x20-\x7e\xa0-ɏḀ-ỿ]', ' ', text)
    # Collapse excessive whitespace
    text = re.sub(r' {3,}', '  ', text)
    return text


def main():
    if len(sys.argv) < 3:
        print("usage: extract_ms_text.py <artifacts_dir> <output_txt>", file=sys.stderr)
        sys.exit(1)

    artifacts_dir = Path(sys.argv[1])
    output_txt = Path(sys.argv[2])

    yamls = sorted(artifacts_dir.rglob('*_transcription.yaml'))
    if not yamls:
        print(f"no YAML files in {artifacts_dir}", file=sys.stderr)
        sys.exit(1)

    chunks = []
    for yf in yamls:
        try:
            data = yaml.safe_load(yf.read_text(encoding='utf-8', errors='replace'))
            out = data.get('transcriptionOutput', {})
            segments = out.get('segments', [])
            page_text = ' '.join(
                seg.get('text', '') for seg in segments
                if isinstance(seg, dict) and seg.get('text')
            )
            if page_text.strip():
                chunks.append(clean(page_text))
        except Exception as e:
            print(f"WARN {yf.name}: {e}", file=sys.stderr)

    combined = '\n\n'.join(chunks)
    output_txt.parent.mkdir(parents=True, exist_ok=True)
    output_txt.write_text(combined, encoding='utf-8')
    word_count = len(combined.split())
    print(f"extracted {len(yamls)} pages, {word_count} words → {output_txt}")


if __name__ == '__main__':
    main()
