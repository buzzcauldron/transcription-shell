#!/usr/bin/env python3
"""Filter CoMMA per-line recognition records into tiers for pseudo-GT extraction.

Two modes (selected automatically):

  CONSENSUS mode (--alto-dir provided):
    Compares our HTR output against CATMuS line text from CoMMA's ALTO XML files.
    Lines where CER(our, CATMuS) < --cer-accept are consensus pseudo-GT.
    Lines where --cer-accept <= CER < --cer-review go to the human review queue.
    Sort key: CER ascending (smallest disagreements first — easiest to adjudicate).

  CONFIDENCE mode (fallback, no --alto-dir):
    Uses Kraken's own per-line confidence score as a quality proxy.
    Lines with conf >= --conf-accept go to pseudo-GT; --conf-review <= conf < accept
    go to review; below that discarded.
    Sort key: confidence descending.

In both modes:
  - Lines containing characters rare or absent in existing GT (<10 occurrences)
    are promoted to the confident tier regardless of score.
  - Character coverage report is always generated.
  - Training firewall: refuses to write into htr-corpora/ or latin-corpus-gt/.

Usage:
    # Consensus mode (preferred — needs ALTO from comma_acquire.sh --with-alto):
    python scripts/comma_filter.py \\
        --lines-jsonl pilot/lines.jsonl \\
        --gt-metadata latin-corpus-gt/metadata.jsonl \\
        --out-dir filtered \\
        --alto-dir raw/comma-alto

    # Confidence-only mode (no ALTO needed):
    python scripts/comma_filter.py \\
        --lines-jsonl pilot/lines.jsonl \\
        --gt-metadata latin-corpus-gt/metadata.jsonl \\
        --out-dir filtered
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# Firewall
# ---------------------------------------------------------------------------

FIREWALL_TOKENS = ("htr-corpora", "latin-corpus-gt")


def _assert_safe_output(path: Path) -> None:
    s = str(path.resolve()).lower()
    for tok in FIREWALL_TOKENS:
        if tok in s:
            sys.exit(
                f"Refusing to write into training tree: {path}\n"
                "Use a comma-rerecognition/ subdirectory instead."
            )


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# CER (normalised edit distance)
# ---------------------------------------------------------------------------

def _cer(a: str, b: str) -> float:
    def norm(s: str) -> str:
        s = unicodedata.normalize("NFD", s)
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return re.sub(r"\s+", " ", s.lower()).strip()

    a, b = norm(a), norm(b)
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    la, lb = len(a), len(b)
    dp = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (ca != cb))
            prev = cur
    return dp[lb] / max(la, lb)


# ---------------------------------------------------------------------------
# ALTO parsing
# ---------------------------------------------------------------------------

# ALTO namespace variants
_ALTO_NS = {
    "alto2": "http://schema.ccs-labs.org/DTD/alto-1-4.dtd",
    "alto3": "http://www.loc.gov/standards/alto/ns-v3#",
    "alto4": "http://www.loc.gov/standards/alto/ns-v4#",
    "noNS":  "",
}


def _strip_ns(tag: str) -> str:
    """Remove XML namespace from a tag like '{http://...}TextLine'."""
    return tag.split("}")[-1] if "}" in tag else tag


def _parse_alto_lines(alto_path: Path) -> list[dict]:
    """Extract per-line records from a CoMMA ALTO XML file.

    Returns list of {text, bbox: [x0, y0, x1, y1]} dicts in reading order.
    """
    try:
        tree = ET.parse(str(alto_path))
    except ET.ParseError as exc:
        print(f"  [alto] parse error {alto_path.name}: {exc}", file=sys.stderr)
        return []

    root = tree.getroot()
    lines: list[dict] = []

    for elem in root.iter():
        if _strip_ns(elem.tag) != "TextLine":
            continue
        try:
            hpos = int(float(elem.get("HPOS", 0)))
            vpos = int(float(elem.get("VPOS", 0)))
            width = int(float(elem.get("WIDTH", 0)))
            height = int(float(elem.get("HEIGHT", 0)))
        except (ValueError, TypeError):
            continue

        # Collect String CONTENT values in order
        parts: list[str] = []
        for child in elem.iter():
            if _strip_ns(child.tag) == "String":
                content = (child.get("CONTENT") or "").strip()
                if content:
                    parts.append(content)
        text = " ".join(parts).strip()
        if not text:
            continue

        lines.append({
            "text": text,
            "bbox": [hpos, vpos, hpos + width, vpos + height],
        })

    return lines


def _iou(a: list[int], b: list[int]) -> float:
    """Intersection-over-union for two [x0,y0,x1,y1] boxes."""
    ix0 = max(a[0], b[0])
    iy0 = max(a[1], b[1])
    ix1 = min(a[2], b[2])
    iy1 = min(a[3], b[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


class AltoIndex:
    """Maps (ms_id, page_idx) → list of ALTO line dicts for fast lookup.

    Alto directory layout expected:
      alto_dir/
        <ms_id>/page_000.xml   (or any basename with zero-padded index)
        <ms_id>/page_001.xml
        ...
    or flat:
      alto_dir/<ms_id>_page_000.xml
    """

    def __init__(self, alto_dir: Path) -> None:
        self._cache: dict[tuple[str, int], list[dict]] = {}
        self._alto_dir = alto_dir
        self._ms_dirs: dict[str, Path] = {}

        # Index available ms_id directories / files
        if alto_dir.is_dir():
            for child in alto_dir.iterdir():
                if child.is_dir():
                    self._ms_dirs[child.name] = child
        print(f"[alto] index: {len(self._ms_dirs)} ms dirs under {alto_dir}")

    def get_lines(self, ms_id: str, page_idx: int) -> list[dict]:
        key = (ms_id, page_idx)
        if key in self._cache:
            return self._cache[key]

        ms_dir = self._ms_dirs.get(ms_id)
        if ms_dir is None:
            # Try partial match (CoMMA ms_ids may be slugified differently)
            slug = re.sub(r"[^\w]", "_", ms_id).lower()
            for name, path in self._ms_dirs.items():
                if re.sub(r"[^\w]", "_", name).lower() == slug:
                    ms_dir = path
                    break

        if ms_dir is None:
            self._cache[key] = []
            return []

        # Find XML for this page index
        xml_files = sorted(ms_dir.glob("*.xml"))
        if page_idx >= len(xml_files):
            self._cache[key] = []
            return []

        result = _parse_alto_lines(xml_files[page_idx])
        self._cache[key] = result
        return result

    def match_line(
        self, ms_id: str, page_idx: int, bbox: list[int] | None, line_idx: int
    ) -> dict | None:
        """Return best-matching ALTO line for a recognized line.

        Matching strategy:
          1. If bbox available: best IoU match (threshold 0.3).
          2. Fallback: same line_idx (order match).
        """
        alto_lines = self.get_lines(ms_id, page_idx)
        if not alto_lines:
            return None

        if bbox is not None:
            best_iou, best_line = 0.0, None
            for al in alto_lines:
                iou = _iou(bbox, al["bbox"])
                if iou > best_iou:
                    best_iou, best_line = iou, al
            if best_iou >= 0.3:
                return best_line

        # Order-based fallback
        if line_idx < len(alto_lines):
            return alto_lines[line_idx]
        return None


# ---------------------------------------------------------------------------
# Coverage analysis
# ---------------------------------------------------------------------------

def _gt_char_counts(gt_metadata_path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not gt_metadata_path.is_file():
        return counts
    for row in _load_jsonl(gt_metadata_path):
        counts.update(row.get("text") or "")
    return counts


def _rare_chars(text: str, gt_counts: Counter[str], threshold: int = 10) -> set[str]:
    return {ch for ch in set(text) if ch.strip() and gt_counts[ch] < threshold}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--lines-jsonl", type=Path, required=True,
                    help="lines.jsonl from comma_recognition_pass.py --save-line-records")
    ap.add_argument("--gt-metadata", type=Path, required=True,
                    help="metadata.jsonl of existing training GT (read-only)")
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="Output dir (must NOT be under htr-corpora or latin-corpus-gt)")
    # Consensus mode
    ap.add_argument("--alto-dir", type=Path, default=None,
                    help="CoMMA ALTO XML directory (enables consensus mode). "
                         "Download with: bash scripts/comma_acquire.sh --with-alto")
    ap.add_argument("--cer-accept", type=float, default=0.05,
                    help="[consensus] CER threshold for auto-GT tier (default 0.05)")
    ap.add_argument("--cer-review", type=float, default=0.30,
                    help="[consensus] CER threshold for review tier (default 0.30)")
    # Confidence mode (fallback)
    ap.add_argument("--conf-accept", type=float, default=0.90,
                    help="[confidence] min confidence for auto-GT tier (default 0.90)")
    ap.add_argument("--conf-review", type=float, default=0.65,
                    help="[confidence] min confidence for review tier (default 0.65)")
    args = ap.parse_args()

    out_dir = args.out_dir.expanduser().resolve()
    _assert_safe_output(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = _load_jsonl(args.lines_jsonl.expanduser().resolve())
    print(f"[filter] {len(lines)} line records from {args.lines_jsonl}")

    gt_counts = _gt_char_counts(args.gt_metadata.expanduser().resolve())
    print(f"[filter] GT vocab: {len(gt_counts)} distinct chars" if gt_counts
          else "[filter] warn: GT metadata empty — coverage analysis skipped")

    # Optional: load ALTO index for consensus mode
    alto_index: AltoIndex | None = None
    consensus_mode = False
    if args.alto_dir is not None:
        alto_dir = args.alto_dir.expanduser().resolve()
        if not alto_dir.is_dir():
            print(f"[filter] warn: --alto-dir {alto_dir} not found — "
                  "falling back to confidence mode", file=sys.stderr)
        else:
            alto_index = AltoIndex(alto_dir)
            consensus_mode = True
            print(f"[filter] CONSENSUS mode (CER vs CATMuS, thresholds "
                  f"accept={args.cer_accept} review={args.cer_review})")

    if not consensus_mode:
        print(f"[filter] CONFIDENCE mode (thresholds "
              f"accept={args.conf_accept} review={args.conf_review})")

    # Per-line rare-char analysis
    rare_char_map: dict[int, set[str]] = {}
    for idx, row in enumerate(lines):
        rare = _rare_chars(row.get("our_text") or "", gt_counts)
        if rare:
            rare_char_map[idx] = rare

    all_rare_chars: set[str] = set().union(*rare_char_map.values()) if rare_char_map else set()

    # Tier each line
    confident: list[dict] = []
    review_queue: list[dict] = []
    low_conf: list[dict] = []
    unmatched_count = 0

    for idx, row in enumerate(lines):
        r = dict(row)
        has_rare = idx in rare_char_map
        if has_rare:
            r["rare_chars"] = sorted(rare_char_map[idx])

        if consensus_mode and alto_index is not None:
            # Consensus mode: score by CER vs CATMuS
            alto_line = alto_index.match_line(
                row.get("ms_id", ""),
                row.get("page_idx", 0),
                row.get("bbox"),
                row.get("line_idx", 0),
            )
            if alto_line is not None:
                cer_val = _cer(row.get("our_text") or "", alto_line["text"])
                r["catmus_text"] = alto_line["text"]
                r["cer_vs_catmus"] = round(cer_val, 4)
                r["score_mode"] = "consensus"

                if has_rare or cer_val < args.cer_accept:
                    confident.append(r)
                elif cer_val < args.cer_review:
                    review_queue.append(r)
                else:
                    low_conf.append(r)
            else:
                # No ALTO match — fall back to confidence for this line
                unmatched_count += 1
                r["score_mode"] = "confidence_fallback"
                conf = float(row.get("confidence") or 0.0)
                if has_rare or conf >= args.conf_accept:
                    confident.append(r)
                elif conf >= args.conf_review:
                    review_queue.append(r)
                else:
                    low_conf.append(r)
        else:
            # Confidence mode
            r["score_mode"] = "confidence"
            conf = float(row.get("confidence") or 0.0)
            if has_rare or conf >= args.conf_accept:
                confident.append(r)
            elif conf >= args.conf_review:
                review_queue.append(r)
            else:
                low_conf.append(r)

    # Sort review queue
    if consensus_mode:
        # Lowest CER first — smallest disagreements, easiest to adjudicate
        review_queue.sort(key=lambda r: float(r.get("cer_vs_catmus") or 1.0))
    else:
        # Highest confidence first
        review_queue.sort(key=lambda r: float(r.get("confidence") or 0.0), reverse=True)

    _write_jsonl(out_dir / "confident.jsonl", confident)
    _write_jsonl(out_dir / "review_queue.jsonl", review_queue)
    _write_jsonl(out_dir / "low_confidence.jsonl", low_conf)

    # Coverage report
    cov_lines = [
        "# CoMMA Character Coverage Report\n",
        f"Mode: {'consensus (CER vs CATMuS)' if consensus_mode else 'confidence-only'}  ",
        f"GT metadata: `{args.gt_metadata}`  ",
        f"CoMMA lines: `{args.lines_jsonl}`  ",
        "",
    ]
    if all_rare_chars:
        cov_lines.append(f"## {len(all_rare_chars)} characters rare or absent in existing GT\n")
        cov_lines.append("| Char | Unicode | GT count | Example lines |")
        cov_lines.append("|------|---------|----------|---------------|")
        for ch in sorted(all_rare_chars):
            ex = [
                f"{lines[i].get('ms_id','?')}:p{lines[i].get('page_idx','?')}l{lines[i].get('line_idx','?')}"
                for i, chars in rare_char_map.items() if ch in chars
            ]
            ex_str = "; ".join(ex[:8]) + (f" … +{len(ex)-8}" if len(ex) > 8 else "")
            cov_lines.append(f"| `{ch}` | U+{ord(ch):04X} | {gt_counts[ch]} | {ex_str} |")
    else:
        cov_lines.append("All CoMMA characters appear ≥10× in existing GT — no coverage gaps.")

    (out_dir / "coverage_report.md").write_text("\n".join(cov_lines) + "\n", encoding="utf-8")

    # Stats
    rare_promoted = sum(
        1 for idx in rare_char_map
        if (consensus_mode
            and float(lines[idx].get("cer_vs_catmus", 1.0)) >= args.cer_accept)
        or (not consensus_mode
            and float(lines[idx].get("confidence", 0.0)) < args.conf_accept)
    )
    stats = {
        "mode": "consensus" if consensus_mode else "confidence",
        "total_lines": len(lines),
        "confident": len(confident),
        "review_queue": len(review_queue),
        "low_confidence": len(low_conf),
        "unmatched_alto": unmatched_count if consensus_mode else None,
        "rare_char_lines_promoted": rare_promoted,
        "rare_chars_found": sorted(all_rare_chars),
        "thresholds": {
            "cer_accept": args.cer_accept,
            "cer_review": args.cer_review,
            "conf_accept": args.conf_accept,
            "conf_review": args.conf_review,
        },
    }
    (out_dir / "filter_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    mode_str = (
        f"cer_accept={args.cer_accept} cer_review={args.cer_review} "
        f"unmatched={unmatched_count}"
        if consensus_mode
        else f"conf_accept={args.conf_accept} conf_review={args.conf_review}"
    )
    print(
        f"[filter] mode={stats['mode']}  confident={len(confident)}  "
        f"review={len(review_queue)}  low={len(low_conf)}  "
        f"rare_promoted={rare_promoted}  {mode_str}"
    )
    print(f"[filter] wrote {out_dir}/")


if __name__ == "__main__":
    main()
