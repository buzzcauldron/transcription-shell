#!/usr/bin/env bash
# Stage 7 — Score: compute CER/WER for expanded pipeline output vs GT XMLs.
#
# Input:   04_expanded/out/*_tei_expanded.xml
# GT:      $LATIN_MS_GT_DIR  (env) or  ~/latin-ms-workspace/training/combined_gt/
# Output:  06_scores/score_report.txt  +  06_scores/score_report.json
#
# Usage:   s7_score.sh [--gt-dir PATH]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

GT_DIR="${LATIN_MS_GT_DIR:-${HOME}/latin-ms-workspace/training/combined_gt}"
JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}"
EXPANDED_DIR="${JOB_DIR}/04_expanded/out"
SCORES_DIR="${JOB_DIR}/06_scores"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --gt-dir) GT_DIR="$2"; shift 2 ;;
        *) echo "Unknown: $1" >&2; exit 1 ;;
    esac
done

mkdir -p "$SCORES_DIR"

python3 - "$EXPANDED_DIR" "$GT_DIR" "$SCORES_DIR" <<'PYEOF'
import sys, re, json, xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime, timezone

expanded_dir, gt_dir, scores_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])

TOKEN_RE = re.compile(
    r'\[(?:illegible|uncertain|gap|damaged|glyph-uncertain|'
    r'deletion|insertion|marginalia|superscript|exp|wrap-join)[^]]*\]'
)

def strip_tokens(text):
    def repl(m):
        tok = m.group(0)
        if tok.startswith("[uncertain:"):
            return tok[len("[uncertain:"):].rstrip("]").strip().split("/")[0].strip()
        return ""
    return TOKEN_RE.sub(repl, text)

def normalize(text):
    return re.sub(r'\s+', ' ', strip_tokens(text)).strip()

def levenshtein(s1, s2):
    if len(s1) < len(s2): return levenshtein(s2, s1)
    if not s2: return len(s1)
    prev = list(range(len(s2)+1))
    for c1 in s1:
        curr = [prev[0]+1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(c1!=c2)))
        prev = curr
    return prev[-1]

def word_lev(a, b):
    if len(a) < len(b): return word_lev(b, a)
    if not b: return len(a)
    prev = list(range(len(b)+1))
    for w1 in a:
        curr = [prev[0]+1]
        for j, w2 in enumerate(b):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(w1!=w2)))
        prev = curr
    return prev[-1]

def extract_gt(xml_path):
    tree = ET.parse(xml_path)
    lines = []
    for tl in tree.getroot().findall('.//{*}TextLine'):
        u = tl.find('{*}TextEquiv/{*}Unicode')
        if u is not None and u.text:
            lines.append(u.text.strip())
    return normalize(' '.join(lines))

def extract_tei(xml_path):
    tree = ET.parse(xml_path)
    texts = []
    for elem in tree.getroot().iter():
        if elem.text and elem.text.strip():
            texts.append(elem.text.strip())
        if elem.tail and elem.tail.strip():
            texts.append(elem.tail.strip())
    return normalize(' '.join(texts))

results = []
total_ced = total_gt_chars = total_wed = total_gt_words = 0

for exp_xml in sorted(expanded_dir.glob("*_tei_expanded.xml")):
    stem = exp_xml.stem.replace("_tei_expanded", "")
    gt_xml = gt_dir / f"{stem}.xml"
    if not gt_xml.exists():
        # Try case-insensitive match
        matches = list(gt_dir.glob(f"{stem}*.xml"))
        if not matches:
            print(f"  [skip] {stem}: no GT found in {gt_dir}")
            continue
        gt_xml = matches[0]

    exp_text = extract_tei(exp_xml)
    gt_text  = extract_gt(gt_xml)
    if not gt_text:
        print(f"  [skip] {stem}: GT has no text")
        continue

    ced = levenshtein(gt_text, exp_text)
    gt_w = gt_text.split(); exp_w = exp_text.split()
    wed = word_lev(gt_w, exp_w)
    cer = ced / len(gt_text) * 100
    wer = wed / len(gt_w) * 100

    sm = SequenceMatcher(None, gt_w, exp_w)
    subs, adds, omits = 0, 0, 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'replace': subs += max(i2-i1, j2-j1)
        elif op == 'insert': adds += j2-j1
        elif op == 'delete': omits += i2-i1

    dispo = "PASS" if cer < 1 and wer < 2 else "COND_PASS" if cer < 3 and wer < 5 else "FAIL"
    results.append({"stem": stem, "cer": round(cer,2), "wer": round(wer,2),
                     "subs": subs, "adds": adds, "omits": omits, "disposition": dispo,
                     "gt_chars": len(gt_text), "gt_words": len(gt_w)})
    total_ced += ced; total_gt_chars += len(gt_text)
    total_wed += wed; total_gt_words += len(gt_w)
    print(f"  {stem:30s}  CER {cer:6.2f}%  WER {wer:6.2f}%  [{dispo}]")

if not results:
    print("  No scoreable cases found.")
    sys.exit(0)

agg_cer = total_ced / total_gt_chars * 100 if total_gt_chars else 0
agg_wer = total_wed / total_gt_words * 100 if total_gt_words else 0
agg_dispo = "PASS" if agg_cer < 1 and agg_wer < 2 else "COND_PASS" if agg_cer < 3 and agg_wer < 5 else "FAIL"

print()
print(f"{'─'*64}")
print(f"  AGGREGATE ({len(results)} cases):")
print(f"  CER {agg_cer:.2f}%   WER {agg_wer:.2f}%   [{agg_dispo}]")
print(f"{'─'*64}")

report = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "cases": results,
    "aggregate": {"cer": round(agg_cer,2), "wer": round(agg_wer,2),
                  "disposition": agg_dispo, "n": len(results)},
}
txt_path = scores_dir / "score_report.txt"
json_path = scores_dir / "score_report.json"
with open(txt_path, "w") as f:
    f.write(f"Score report  {report['timestamp']}\n\n")
    for r in results:
        f.write(f"  {r['stem']:30s}  CER {r['cer']:6.2f}%  WER {r['wer']:6.2f}%  [{r['disposition']}]\n")
    f.write(f"\nAggregate: CER {agg_cer:.2f}%  WER {agg_wer:.2f}%  [{agg_dispo}]\n")
with open(json_path, "w") as f:
    json.dump(report, f, indent=2)

print(f"\n  Reports: {txt_path}")
PYEOF

echo ""
echo "========================================================"
echo "  Stage 7 done. Scores in: ${SCORES_DIR}"
echo "========================================================"
