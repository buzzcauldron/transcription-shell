#!/usr/bin/env bash
# Stage 8 — Compare expanded: pipeline output vs human diplomatic GT,
# both expanded by expand-diplomatic. True apples-vs-apples CER.
#
# Input:
#   04_expanded/out/{stem}_tei_expanded.xml  (pipeline expanded)
#   ground_truth/diplomatic/{stem}_diplomatic.txt  (human diplomatic GT)
#
# Output:
#   06_scores/ex_vs_ex_{stem}.json + printed table
#
# Usage:
#   LATIN_MS_JOB_ID=myjob LATIN_MS_GT_STEM=JUST1-633m5 bash s8_compare_expanded.sh
#   bash s8_compare_expanded.sh --job-id myjob --stem JUST1-633m5 [--passes 2]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

JOB_ID="${LATIN_MS_JOB_ID:-}"
STEM="${LATIN_MS_GT_STEM:-}"
PASSES="${EXPAND_DIPLOMATIC_PASSES:-1}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --job-id) JOB_ID="$2"; shift 2 ;;
        --stem)   STEM="$2";   shift 2 ;;
        --passes) PASSES="$2"; shift 2 ;;
        *) echo "Unknown: $1" >&2; exit 1 ;;
    esac
done

[[ -z "$JOB_ID" ]] && { echo "ERROR: set LATIN_MS_JOB_ID or --job-id" >&2; exit 1; }
[[ -z "$STEM"   ]] && { echo "ERROR: set LATIN_MS_GT_STEM or --stem" >&2; exit 1; }

JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${JOB_ID}"
EXPANDED_DIR="${JOB_DIR}/04_expanded/out"
SCORES_DIR="${JOB_DIR}/06_scores"
DIPLOMATIC_GT="${REPO_ROOT}/ground_truth/diplomatic/${STEM}_diplomatic.txt"
MAGIC_ELISE="${EXPAND_DIPLOMATIC_ROOT:-${MAGIC_ELISE_ROOT:-${HOME}/Projects/expand-diplomatic}}"

mkdir -p "$SCORES_DIR"

[[ ! -f "$DIPLOMATIC_GT" ]] && {
    echo "ERROR: no diplomatic GT at ${DIPLOMATIC_GT}"
    echo "  Add ${STEM}_diplomatic.txt to ground_truth/diplomatic/"
    exit 1
}

# Export the working Gemini key for expand-diplomatic
_TS_GKEY="$(python3 -c "from transcriber_shell.config import Settings; s=Settings(); print(s.google_api_key or '')" 2>/dev/null)"
[[ -n "$_TS_GKEY" ]] && { export GOOGLE_API_KEY="$_TS_GKEY"; unset GEMINI_API_KEY 2>/dev/null || true; }

echo "========================================================"
echo "  Stage 8: ex-vs-ex comparison"
echo "  Job:     ${JOB_ID}  |  Stem: ${STEM}"
echo "  Passes:  ${PASSES}"
echo "========================================================"

# ── 1. Expand human diplomatic GT ────────────────────────────────────────────
GT_TEI_DIR="${JOB_DIR}/.gt_tei_stage"
GT_EXPANDED_DIR="${JOB_DIR}/.gt_expanded"
mkdir -p "$GT_TEI_DIR" "$GT_EXPANDED_DIR"

echo "==> Converting human diplomatic GT → TEI..."
python3 - "$DIPLOMATIC_GT" "$GT_TEI_DIR/${STEM}_tei.xml" <<'PYEOF'
import sys
from pathlib import Path

txt_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
lines = [l.rstrip('\n') for l in txt_path.read_text(encoding='utf-8').splitlines()]
segs = '\n    '.join(f'<ab n="{i+1}">{l}</ab>' for i, l in enumerate(lines))
tei = f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body>
      {segs}
    </body>
  </text>
</TEI>
"""
Path(out_path).parent.mkdir(parents=True, exist_ok=True)
Path(out_path).write_text(tei, encoding='utf-8')
print(f"  {len(lines)} lines → {out_path}")
PYEOF

echo "==> Expanding human diplomatic GT..."
(cd "$MAGIC_ELISE" && python3 -m expand_diplomatic \
    --batch-dir "$GT_TEI_DIR" \
    --out-dir "$GT_EXPANDED_DIR" \
    --backend gemini \
    --modality full \
    --passes "$PASSES" \
    --model "${EXPAND_DIPLOMATIC_MODEL:-gemini-2.5-flash}" \
    2>&1)

# ── 2. Locate pipeline expanded XML ──────────────────────────────────────────
PIPE_XML="${EXPANDED_DIR}/${STEM}_tei_expanded.xml"
GT_XML="${GT_EXPANDED_DIR}/${STEM}_tei_expanded.xml"

[[ ! -f "$PIPE_XML" ]] && { echo "ERROR: pipeline expanded XML not found: ${PIPE_XML}"; exit 1; }
[[ ! -f "$GT_XML"   ]] && { echo "ERROR: GT expanded XML not found: ${GT_XML}"; exit 1; }

# ── 3. Score ──────────────────────────────────────────────────────────────────
echo ""
echo "==> Scoring..."
python3 - "$PIPE_XML" "$GT_XML" "$SCORES_DIR" "$STEM" <<'PYEOF'
import sys, re, json, xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher

pipe_xml, gt_xml, scores_dir, stem = sys.argv[1:5]
scores_dir = Path(scores_dir)

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

def extract_tei(path):
    tree = ET.parse(path)
    parts = []
    for elem in tree.getroot().iter():
        if elem.text and elem.text.strip():
            parts.append(elem.text.strip())
        if elem.tail and elem.tail.strip():
            parts.append(elem.tail.strip())
    return normalize(' '.join(parts))

def levenshtein(s1, s2):
    if len(s1) < len(s2): return levenshtein(s2, s1)
    if not s2: return len(s1)
    prev = list(range(len(s2)+1))
    for c1 in s1:
        curr = [prev[0]+1]
        for j,c2 in enumerate(s2):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(c1!=c2)))
        prev = curr
    return prev[-1]

def word_lev(a, b):
    if len(a) < len(b): return word_lev(b, a)
    if not b: return len(a)
    prev = list(range(len(b)+1))
    for w1 in a:
        curr = [prev[0]+1]
        for j,w2 in enumerate(b):
            curr.append(min(prev[j+1]+1, curr[j]+1, prev[j]+(w1!=w2)))
        prev = curr
    return prev[-1]

pipe = extract_tei(pipe_xml)
gt   = extract_tei(gt_xml)

ced = levenshtein(gt, pipe)
gt_w = gt.split(); pipe_w = pipe.split()
wed = word_lev(gt_w, pipe_w)
cer = ced / len(gt) * 100 if gt else 0
wer = wed / len(gt_w) * 100 if gt_w else 0

sm = SequenceMatcher(None, gt_w, pipe_w)
subs, adds, omits = 0, 0, 0
for op, i1, i2, j1, j2 in sm.get_opcodes():
    if op == 'replace': subs += max(i2-i1, j2-j1)
    elif op == 'insert': adds += j2-j1
    elif op == 'delete': omits += i2-i1

dispo = "PASS" if cer < 1 and wer < 2 else "COND_PASS" if cer < 3 and wer < 5 else "FAIL"

print(f"  ┌─────────────────────────────────────────────────────────┐")
print(f"  │ EX vs EX: {stem:<46s} │")
print(f"  │ CER {cer:6.2f}%  ({ced} edits / {len(gt)} chars)                   │")
print(f"  │ WER {wer:6.2f}%  ({wed} edits / {len(gt_w)} words)                   │")
print(f"  │ Subs {subs:4d}  Adds {adds:4d}  Omits {omits:4d}                       │")
print(f"  │ {dispo:<56s} │")
print(f"  └─────────────────────────────────────────────────────────┘")

# Top substitutions
print("\n  Top word substitutions (GT → pipeline):")
sub_list = []
for op, i1, i2, j1, j2 in SequenceMatcher(None, gt_w, pipe_w).get_opcodes():
    if op == 'replace':
        for k in range(max(i2-i1, j2-j1)):
            gw = gt_w[i1+k] if i1+k < i2 else ""
            pw = pipe_w[j1+k] if j1+k < j2 else ""
            if gw and pw and gw != pw:
                sub_list.append((gw, pw))
for g, p in sub_list[:15]:
    print(f"    '{g}' → '{p}'")

report = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "stem": stem,
    "comparison": "expanded_pipeline_vs_expanded_human_diplomatic_gt",
    "cer": round(cer, 2), "wer": round(wer, 2),
    "edits": ced, "gt_chars": len(gt), "word_edits": wed, "gt_words": len(gt_w),
    "subs": subs, "adds": adds, "omits": omits,
    "disposition": dispo,
}
out = scores_dir / f"ex_vs_ex_{stem}.json"
out.write_text(json.dumps(report, indent=2))
print(f"\n  Report: {out}")
PYEOF

echo ""
echo "========================================================"
echo "  Stage 8 done."
echo "========================================================"
