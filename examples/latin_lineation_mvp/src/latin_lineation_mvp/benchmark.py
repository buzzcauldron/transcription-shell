"""Compare hypothesis lines.xml to a Glyph Machina reference (installed with transcriber-shell)."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    try:
        from transcriber_shell.xml_tools.lines_compare import (
            compare_lines_xml,
            format_comparison_report,
        )
    except ImportError:
        print(
            "Install transcriber-shell (editable) to use this command, "
            "or run: python scripts/benchmark_gm_parity.py",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    p = argparse.ArgumentParser(description="GM parity: reference vs hypothesis PageXML")
    p.add_argument("--reference", "-r", type=str, required=True)
    p.add_argument("--hypothesis", "-y", type=str, required=True)
    p.add_argument("--centroid-match-px", type=float, default=120.0)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    result = compare_lines_xml(
        args.reference,
        args.hypothesis,
        centroid_match_px=args.centroid_match_px,
    )
    print(format_comparison_report(result, as_json=args.json))


if __name__ == "__main__":
    main()
