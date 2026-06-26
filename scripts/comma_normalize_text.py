#!/usr/bin/env python3
"""Apply CoMMA ByT5 pre-editorial normalization to HTR or plain text lines.

Model: comma-project/normalization-byt5-small (Latin + Old French).

Usage:
  echo "Scͥbo uobiᷤᷤ ñ pauli ł donati." | python scripts/comma_normalize_text.py
  python scripts/comma_normalize_text.py --in lines.txt --out normalized.txt
  python scripts/comma_normalize_text.py --in htr.jsonl --out norm.jsonl --field text

Install: pip install 'transcriber-shell[comma]'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from transcriber_shell.comma.normalize import DEFAULT_MODEL, normalize_medieval_text  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="in_path", type=Path, help="Input file (one line per row, or JSONL)")
    ap.add_argument("--out", dest="out_path", type=Path, help="Output file (default: stdout)")
    ap.add_argument("--field", default="text", help="JSONL field to normalize (default: text)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="HF model id")
    ap.add_argument("--jsonl", action="store_true", help="Treat input as JSONL (one object per line)")
    args = ap.parse_args()

    def emit(line: str) -> None:
        if args.out_path:
            with args.out_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        else:
            print(line)

    if args.out_path:
        args.out_path.parent.mkdir(parents=True, exist_ok=True)
        args.out_path.write_text("", encoding="utf-8")

    if args.in_path:
        raw_lines = args.in_path.read_text(encoding="utf-8").splitlines()
    else:
        raw_lines = sys.stdin.read().splitlines()

    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        if args.jsonl or (args.in_path and args.in_path.suffix == ".jsonl"):
            row = json.loads(raw)
            src = row.get(args.field, "")
            row[f"{args.field}_normalized"] = normalize_medieval_text(str(src), model_id=args.model)
            emit(json.dumps(row, ensure_ascii=False))
        else:
            emit(normalize_medieval_text(raw, model_id=args.model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
