#!/usr/bin/env bash
# Post-training hook: eval, update docs/MODELS.md, git push.
# Called at the end of every training sbatch job.
#
# Usage:
#   bash scripts/bridges_post_training.sh \
#     --model-name gm-htr-r6-core \
#     --model-path /ocean/.../gm-htr-r6-core_best.mlmodel \
#     --val-manifest /ocean/.../latin-corpus-gt/core_val_manifest.txt \
#     --round r6-core \
#     --base gm-htr-r2_best \
#     --notes "Phase 1: clean medieval Latin corpus"
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
REPO="$SRC"

MODEL_NAME=""
MODEL_PATH=""
VAL_MANIFEST=""
ROUND=""
BASE=""
NOTES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model-name)    MODEL_NAME="$2";    shift 2 ;;
    --model-path)    MODEL_PATH="$2";    shift 2 ;;
    --val-manifest)  VAL_MANIFEST="$2";  shift 2 ;;
    --round)         ROUND="$2";         shift 2 ;;
    --base)          BASE="$2";          shift 2 ;;
    --notes)         NOTES="$2";         shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -f "$MODEL_PATH" ]] || { echo "[post] model not found: $MODEL_PATH — skipping"; exit 0; }

source "$SRC/scripts/bridges_kraken_activate.sh"

# 1. ketos test: get final char accuracy on the val manifest
CHAR_ACC=""
WORD_ACC=""
if [[ -s "$VAL_MANIFEST" ]]; then
  echo "[post] running ketos test on $(wc -l < "$VAL_MANIFEST") val lines..."
  TEST_OUT=$(ketos test -m "$MODEL_PATH" -f page -e "$VAL_MANIFEST" 2>&1 || true)
  echo "$TEST_OUT"
  CHAR_ACC=$(echo "$TEST_OUT" | grep -oP 'Character accuracy: \K[\d.]+' | tail -1 || true)
  WORD_ACC=$(echo "$TEST_OUT"  | grep -oP 'Word accuracy: \K[\d.]+' | tail -1 || true)
fi

CHAR_ACC="${CHAR_ACC:-unknown}"
WORD_ACC="${WORD_ACC:-unknown}"
echo "[post] char_acc=$CHAR_ACC word_acc=$WORD_ACC"

# 2. Write summary JSON
SUMMARY="$SRC/_training_complete_${MODEL_NAME}.json"
python3 - <<PYEOF
import json, pathlib
s = {
    "model_name": "$MODEL_NAME",
    "model_path": "$MODEL_PATH",
    "round": "$ROUND",
    "base": "$BASE",
    "val_manifest": "$VAL_MANIFEST",
    "char_acc": "$CHAR_ACC",
    "word_acc": "$WORD_ACC",
    "notes": "$NOTES",
}
pathlib.Path("$SUMMARY").write_text(json.dumps(s, indent=2) + "\n")
print(f"[post] wrote $SUMMARY")
PYEOF

# 3. Update docs/MODELS.md in-repo and push if GitHub SSH is available
cd "$REPO"

if ! git remote get-url origin &>/dev/null; then
  echo "[post] no git remote — skipping GitHub push"
  exit 0
fi

if ! ssh -o BatchMode=yes -o ConnectTimeout=5 git@github.com true 2>/dev/null; then
  echo "[post] GitHub SSH not available on this node — model summary written to $SUMMARY"
  echo "[post] Pull it on your Mac with: scp sstrickland@bridges2.psc.edu:$SUMMARY ."
  exit 0
fi

git pull --ff-only origin main

# Append row to the HTR table in docs/MODELS.md
python3 - <<'PYEOF'
import json, pathlib, re, sys

s = json.loads(pathlib.Path("$SUMMARY").read_text())
char_acc = s["char_acc"]
word_acc  = s["word_acc"]
try:
    cer = f"{(1-float(char_acc))*100:.1f} %" if char_acc != "unknown" else "—"
    wer = f"{(1-float(word_acc))*100:.1f} %"  if word_acc  != "unknown" else "—"
except Exception:
    cer = wer = "—"

new_row = (
    f"| `{s['model_name']}` | medieval Latin (Bridges r6/r7 pipeline) "
    f"| `{s['base']}` | {s['round']} | — | {cer} | {wer} |"
)

md = pathlib.Path("$REPO/docs/MODELS.md")
text = md.read_text()

# Insert before the closing of the HTR table (first blank line after the table)
marker = "| `gm-hf-htr_best`"
if s["model_name"] in text:
    print(f"[post] {s['model_name']} already in MODELS.md — skipping row insert")
elif marker in text:
    text = text.replace(marker, new_row + "\n" + marker)
    md.write_text(text)
    print(f"[post] inserted row for {s['model_name']}")
else:
    print(f"[post] WARN: could not find insertion point in MODELS.md — append manually")
    print(new_row)
    sys.exit(0)
PYEOF

git add docs/MODELS.md
git diff --cached --quiet && echo "[post] no changes to commit" && exit 0

git commit -m "chore(models): add ${MODEL_NAME} to MODELS.md (${CHAR_ACC} char acc)"
git push origin main
echo "[post] pushed to GitHub"
