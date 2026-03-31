#!/usr/bin/env python3
"""Compare local lines.xml to a Glyph Machina (or other) reference PageXML.

Example:
  python scripts/benchmark_gm_parity.py \\
    --reference artifacts/gm-job/lines.xml \\
    --hypothesis artifacts/local-job/lines.xml \\
    --centroid-match-px 120

Or use: transcriber-shell compare-lines-xml -r ref.xml -y hyp.xml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from transcriber_shell.xml_tools.lines_compare import (  # noqa: E402
    compare_lines_xml,
    format_comparison_report,
)


def main() -> int:
    p = argparse.ArgumentParser(description="GM parity: reference vs hypothesis PageXML")
    p.add_argument("--reference", "-r", type=Path, required=True, help="Ground truth (e.g. GM download)")
    p.add_argument("--hypothesis", "-y", type=Path, required=True, help="Local mask output lines.xml")
    p.add_argument("--centroid-match-px", type=float, default=120.0)
    p.add_argument("--json", action="store_true", help="JSON report")
    args = p.parse_args()

    result = compare_lines_xml(
        args.reference,
        args.hypothesis,
        centroid_match_px=args.centroid_match_px,
    )
    print(format_comparison_report(result, as_json=args.json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
