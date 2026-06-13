#!/usr/bin/env bash
# Regularize the Latin HTR corpus on Bridges2 and stage r6 training manifests.
# Called from r6_core_retrain.sbatch / r7_full_retrain.sbatch on a compute node.
# Do NOT run this directly on a Bridges login node.
#
# Environment:
#   SRC                       transcriber-shell src root (default: /ocean/.../src)
#   VENV                      kraken venv (default: $SRC/../kraken-venv)
#   SKIP_BULLINGER_EXTRACT=1  skip zip extract (set in r6-core, unset in r7-full)

set -euo pipefail

SRC="${SRC:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
GT_MSS="${GT_MSS:-$SRC/../gt-mss}"
CORPORA="$SRC/htr-corpora"
GT="$SRC/latin-corpus-gt"
R6="$SRC/r6"
HERE="$(cd "$(dirname "$0")" && pwd)"

# shellcheck disable=SC1091
source "$HERE/bridges_prep_env.sh"

cd "$SRC"
echo "[prep] python: $($PY_RUN --version 2>&1) at $(which "$PY_RUN" 2>/dev/null || echo "$PY_RUN")"
echo "[prep] cwd:          $(pwd)  (expect: $SRC)"
echo "[prep] corpora root: $CORPORA"
echo "[prep] gt-mss root:  $GT_MSS"
echo "[prep] output GT:    $GT"

if [[ ! -d "$CORPORA" ]]; then
  echo "ERROR: htr-corpora missing. Finish akdeniz -> Bridges rsync first." >&2
  exit 1
fi
if [[ ! -f "$HERE/regularize_latin_htr_corpus.py" ]]; then
  echo "ERROR: run from $SRC or use scripts/bridges_quickstart.sh (absolute paths)." >&2
  exit 1
fi

# pyyaml is already in the kraken venv — no pip install needed
"$PY_RUN" -c "import yaml" 2>/dev/null || "$PY_RUN" -m pip install -q pyyaml

EXTRACT_ARGS=()
if [[ "${SKIP_BULLINGER_EXTRACT:-0}" != "1" ]]; then
  EXTRACT_ARGS=(--extract-bullinger)
else
  echo "[prep] SKIP_BULLINGER_EXTRACT=1 — skipping zip extract (r6-core does not need it)"
fi

"$PY_RUN" "$HERE/regularize_latin_htr_corpus.py" \
  --corpora-root "$CORPORA" \
  --out-dir "$GT" \
  --src-root "$SRC" \
  --gt-mss-root "$GT_MSS" \
  "${EXTRACT_ARGS[@]}" \
  --workers 8

"$PY_RUN" "$HERE/split_retrain_manifests.py" --gt-dir "$GT"

mkdir -p "$R6"
ln -sf "$GT/full_train_manifest.txt" "$R6/r6_train.txt"
ln -sf "$GT/full_val_manifest.txt"   "$R6/r6_val.txt"

echo "[prep] manifests:"
echo "  full train: $(wc -l < "$GT/full_train_manifest.txt")"
echo "  full val:   $(wc -l < "$GT/full_val_manifest.txt")"
echo "  core train: $(wc -l < "$GT/core_train_manifest.txt")"
echo "  bullinger:  $(wc -l < "$GT/bullinger_train_manifest.txt") train / $(wc -l < "$GT/bullinger_val_manifest.txt") val"
if [[ -f "$GT/gothic_bible_train_manifest.txt" ]]; then
  echo "  gothic bible: $(wc -l < "$GT/gothic_bible_train_manifest.txt") train / $(wc -l < "$GT/gothic_bible_val_manifest.txt") val"
fi
echo "[prep] audit:       $GT/audit.md"
echo "[prep] retrain plan: $GT/retrain_plan.json"
echo "[prep] done."
echo "[prep] Significant retrain (recommended):"
echo "       sbatch $SRC/scripts/r6_core_retrain.sbatch"
echo "       sbatch --dependency=afterok:<jobid> $SRC/scripts/r7_full_retrain.sbatch"
echo "[prep] Light fine-tune (not recommended after corpus rebuild): sbatch $R6/r6.sbatch"
