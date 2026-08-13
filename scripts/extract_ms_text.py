#!/usr/bin/env python3
"""Extract Latin transcription text from a job's artifact directory.

Reads all *_transcription.yaml files, concatenates segment text fields,
and writes a single plain-text file suitable for stylo input.

Use ``--page-markers --raw`` for a review/collation export that preserves
page identity and diplomatic Unicode. The default remains a cleaned,
marker-free stylometry export.
"""
import argparse
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


def transcription_output(data):
    out = data.get('transcriptionOutput', data) if isinstance(data, dict) else data
    if isinstance(out, str):
        nested = yaml.safe_load(out)
        return nested if isinstance(nested, dict) else {}
    return out if isinstance(out, dict) else {}


def page_id(path: Path) -> str:
    return re.sub(r'_transcription$', '', path.stem)


def expanded_candidates(yaml_path: Path, artifacts_dir: Path) -> list[Path]:
    """Sidecar expanded plain text written by batch expand / expand-diplomatic."""
    stem = page_id(yaml_path)
    job_root = artifacts_dir.parent
    return [
        job_root / "04_expanded" / f"{stem}_expanded.txt",
        job_root / "04_expanded" / f"{stem}_tei_expanded.txt",
        yaml_path.parent / f"{stem}_expanded.txt",
    ]


def yaml_page_text(yaml_path: Path) -> str:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8", errors="replace"))
    out = transcription_output(data)
    segments = out.get("segments", [])
    return " ".join(
        seg.get("text", "")
        for seg in segments
        if isinstance(seg, dict) and seg.get("text")
    )


def load_page_text(
    yaml_path: Path,
    artifacts_dir: Path,
    *,
    prefer_expanded: bool,
) -> tuple[str, str]:
    """Return (text, source) where source is 'expanded' or 'yaml'."""
    if prefer_expanded:
        for cand in expanded_candidates(yaml_path, artifacts_dir):
            if cand.is_file() and cand.stat().st_size > 0:
                text = cand.read_text(encoding="utf-8", errors="replace")
                if text.strip():
                    return text, "expanded"
    return yaml_page_text(yaml_path), "yaml"


def natural_key(path: Path) -> list[object]:
    """Sort f2 before f10 while retaining deterministic text ordering."""
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r'(\d+)', str(path))
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts_dir', type=Path)
    parser.add_argument('output_txt', type=Path)
    parser.add_argument(
        '--page-markers',
        action='store_true',
        help='Prefix each nonempty page with a stable source-page marker.',
    )
    parser.add_argument(
        '--raw',
        action='store_true',
        help='Preserve diplomatic Unicode instead of applying stylometry cleanup.',
    )
    parser.add_argument(
        '--prefer-expanded',
        '--for-stylo',
        dest='prefer_expanded',
        action='store_true',
        help=(
            'Prefer 04_expanded/*_expanded.txt (or sidecar) over diplomatic YAML. '
            'Falls back to YAML when expanded text is missing. Alias: --for-stylo.'
        ),
    )
    args = parser.parse_args()

    artifacts_dir = args.artifacts_dir
    output_txt = args.output_txt

    yamls = sorted(artifacts_dir.rglob('*_transcription.yaml'), key=natural_key)
    if not yamls:
        print(f"no YAML files in {artifacts_dir}", file=sys.stderr)
        sys.exit(1)

    chunks = []
    n_expanded = 0
    n_yaml = 0
    for yf in yamls:
        try:
            page_text, source = load_page_text(
                yf, artifacts_dir, prefer_expanded=args.prefer_expanded
            )
            if page_text.strip():
                text = page_text if args.raw else clean(page_text)
                if args.page_markers:
                    text = f"===== PAGE {page_id(yf)} =====\n\n{text}"
                chunks.append(text)
                if source == "expanded":
                    n_expanded += 1
                else:
                    n_yaml += 1
        except Exception as e:
            print(f"WARN {yf.name}: {e}", file=sys.stderr)

    combined = '\n\n'.join(chunks)
    output_txt.parent.mkdir(parents=True, exist_ok=True)
    output_txt.write_text(combined, encoding='utf-8')
    word_count = len(combined.split())
    print(
        f"extracted {len(yamls)} pages ({n_expanded} expanded, {n_yaml} yaml), "
        f"{word_count} words → {output_txt}"
    )


if __name__ == '__main__':
    main()
