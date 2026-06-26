#!/usr/bin/env bash
# Export the best Lightning checkpoint in a ketos train output dir to .mlmodel.
#
# Picks checkpoint_NN-VAL.ckpt with highest VAL (filename suffix). Skips checkpoint_abort.
#
# Usage:
#   bash scripts/bridges_export_kraken_checkpoint.sh DIR/ OUT.mlmodel
set -euo pipefail

CKPT_DIR="${1:?checkpoint dir}"
OUT="${2:?output .mlmodel path}"

SRC="${SRC:-$(cd "$(dirname "$0")/.." && pwd)}"
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"

mapfile -t CKPTS < <(find "$CKPT_DIR" -maxdepth 1 -name 'checkpoint_*.ckpt' ! -name 'checkpoint_abort.ckpt' 2>/dev/null | sort)
[[ ${#CKPTS[@]} -gt 0 ]] || { echo "[export-ckpt] no checkpoints in $CKPT_DIR" >&2; exit 1; }

best=""
best_val=""
for f in "${CKPTS[@]}"; do
  base=$(basename "$f")
  val=$(sed -n 's/^checkpoint_[0-9]*-\([0-9.]*\)\.ckpt$/\1/p' <<<"$base")
  [[ -n "$val" ]] || continue
  if [[ -z "$best_val" ]] || awk -v a="$val" -v b="$best_val" 'BEGIN{exit !(a>b)}'; then
    best_val="$val"
    best="$f"
  fi
done
[[ -n "$best" ]] || { echo "[export-ckpt] could not parse checkpoint names in $CKPT_DIR" >&2; exit 1; }

mkdir -p "$(dirname "$OUT")"
echo "[export-ckpt] $best (val=$best_val) → $OUT"
ketos convert -o "$OUT" --weights-format coreml "$best"
echo "[export-ckpt] done $(wc -c < "$OUT") bytes"
