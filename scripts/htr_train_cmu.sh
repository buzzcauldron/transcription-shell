#!/usr/bin/env bash
# Sync HuggingFace ground truth to CMU server and launch ketos train for HTR.
#
# Usage:
#   export CMU_HOST=user@host.andrew.cmu.edu
#   ./scripts/htr_train_cmu.sh
#
# Options (env vars):
#   CMU_HOST          SSH target (required)
#   CMU_GT_DIR        Remote ground truth directory (default: ~/src/gm-hf-gt)
#   CMU_OUT_MODEL     Remote output model path (default: ~/src/gm-hf-htr.mlmodel)
#   CMU_BASE_MODEL    Remote base model to fine-tune from (default: ~/src/latin_documents/transfer_learned_1k_lines.mlmodel)
#   LOCAL_GT_DIR      Local GT directory to sync (default: ~/src/gm-hf-gt)
#   CMU_DEVICE        ketos device string (default: cuda:0)
#   CMU_EPOCHS        Max epochs per run (default: 150)
#   CMU_PRECISION     ketos precision flag (default: bf16-mixed)
#   CMU_WORKERS       DataLoader workers (default: 4)
#   SKIP_SYNC         Set to 1 to skip rsync (GT already on server)
#   CMU_LRATE         Learning rate (default: 0.0001 — good for fine-tuning)
#   CMU_LAG           Early-stopping patience in epochs (default: 20)
#   CMU_FREEZE        Freeze backbone for first N samples (default: 3603)
#
# Round-2 example (continue from HF-trained model on new GT):
#   CMU_HOST=seth@akdeniz.lan.cmu.edu \
#   CMU_BASE_MODEL=~/src/gm-hf-htr_best.mlmodel \
#   LOCAL_GT_DIR=~/src/round2-gt \
#   CMU_GT_DIR=~/src/round2-gt \
#   CMU_OUT_MODEL=~/src/gm-hf-htr-r2.mlmodel \
#   ./scripts/htr_train_cmu.sh

set -euo pipefail

: "${CMU_HOST:?Set CMU_HOST to user@host.andrew.cmu.edu}"
CMU_GT_DIR="${CMU_GT_DIR:-~/src/gm-hf-gt}"
CMU_OUT_MODEL="${CMU_OUT_MODEL:-~/src/gm-hf-htr.mlmodel}"
CMU_BASE_MODEL="${CMU_BASE_MODEL:-~/src/latin_documents/transfer_learned_1k_lines.mlmodel}"
LOCAL_GT_DIR="${LOCAL_GT_DIR:-$HOME/src/gm-hf-gt}"
CMU_DEVICE="${CMU_DEVICE:-cuda:0}"
CMU_EPOCHS="${CMU_EPOCHS:-150}"
CMU_PRECISION="${CMU_PRECISION:-bf16-mixed}"
CMU_WORKERS="${CMU_WORKERS:-4}"
SKIP_SYNC="${SKIP_SYNC:-0}"
CMU_LRATE="${CMU_LRATE:-0.0001}"
CMU_LAG="${CMU_LAG:-20}"
CMU_FREEZE="${CMU_FREEZE:-3603}"

echo "CMU host:     $CMU_HOST"
echo "Remote GT:    $CMU_GT_DIR"
echo "Base model:   $CMU_BASE_MODEL"
echo "Output:       $CMU_OUT_MODEL"
echo "Device:       $CMU_DEVICE  precision: $CMU_PRECISION"
echo ""

# ── 1. Sync ground truth ──────────────────────────────────────────────────

if [[ "$SKIP_SYNC" != "1" ]]; then
  if [[ ! -d "$LOCAL_GT_DIR" ]]; then
    echo "Local GT not found: $LOCAL_GT_DIR" >&2
    echo "Run first: python scripts/prepare_hf_htr_train.py --out $LOCAL_GT_DIR" >&2
    exit 1
  fi
  echo "Syncing GT to $CMU_HOST:$CMU_GT_DIR …"
  rsync -avz --progress "$LOCAL_GT_DIR/" "$CMU_HOST:$CMU_GT_DIR/"
  echo ""
fi

# ── 2. Verify GT directory exists on server ──────────────────────────────

ssh "$CMU_HOST" bash <<REMOTE_CHECK
set -euo pipefail
cd "$CMU_GT_DIR" 2>/dev/null || { echo "GT dir not found on server: $CMU_GT_DIR"; exit 1; }
train_count=\$(ls train/*.xml 2>/dev/null | wc -l)
echo "Train XMLs: \$train_count"
if [[ "\$train_count" -eq 0 ]]; then
  echo "No train/*.xml files found in $CMU_GT_DIR/train/" >&2; exit 1
fi
REMOTE_CHECK

# ── 3. Train ─────────────────────────────────────────────────────────────

echo ""
echo "Launching ketos train on $CMU_HOST …"

# Build validation file list on server (test/ or validation/ subdirectory)
VAL_FLAG=""
ssh "$CMU_HOST" bash <<REMOTE_VALCHECK
set -euo pipefail
val_list="$CMU_GT_DIR/val_list.txt"
{ ls "$CMU_GT_DIR/test/"*.xml 2>/dev/null; ls "$CMU_GT_DIR/validation/"*.xml 2>/dev/null; } > "\$val_list" || true
count=\$(wc -l < "\$val_list")
if [[ "\$count" -gt 0 ]]; then
  echo "Validation XMLs: \$count (written to \$val_list)"
else
  rm -f "\$val_list"
  echo "No validation XMLs found — will split from train set."
fi
REMOTE_VALCHECK

if ssh "$CMU_HOST" "test -f '$CMU_GT_DIR/val_list.txt'" 2>/dev/null; then
  VAL_FLAG="-e '$CMU_GT_DIR/val_list.txt'"
fi

ssh "$CMU_HOST" bash <<REMOTE_TRAIN
set -euo pipefail
cd ~

# Check base model
if [[ ! -f "$CMU_BASE_MODEL" ]]; then
  echo "Base model not found: $CMU_BASE_MODEL"
  echo "Set CMU_BASE_MODEL or copy transfer_learned_1k_lines.mlmodel to the server."
  exit 1
fi

echo "Base model:  $CMU_BASE_MODEL"
echo "Output:      $CMU_OUT_MODEL"
echo "Train XML:   $CMU_GT_DIR/train/*.xml"
echo ""

export PYTORCH_ALLOC_CONF=expandable_segments:True

ketos train \
  -i "$CMU_BASE_MODEL" \
  --resize union \
  -f page \
  -q early \
  --lag $CMU_LAG \
  --min-epochs 10 \
  -N $CMU_EPOCHS \
  -B 32 \
  -r $CMU_LRATE \
  --schedule reduceonplateau \
  --sched-patience 5 \
  --freeze-backbone $CMU_FREEZE \
  --augment \
  -d $CMU_DEVICE \
  --workers $CMU_WORKERS \
  $VAL_FLAG \
  -o "$CMU_OUT_MODEL" \
  "$CMU_GT_DIR/train"/*.xml

echo ""
echo "Training complete."
best="\${CMU_OUT_MODEL%.mlmodel}_best.mlmodel"
if [[ -f "\$best" ]]; then
  echo "Best checkpoint: \$best"
else
  echo "Output: $CMU_OUT_MODEL"
fi
REMOTE_TRAIN

# ── 4. Copy result back ───────────────────────────────────────────────────

BEST_REMOTE="${CMU_OUT_MODEL%.mlmodel}_best.mlmodel"
LOCAL_OUT="$HOME/src/$(basename "$BEST_REMOTE")"

echo ""
echo "Copying best model back: $CMU_HOST:$BEST_REMOTE → $LOCAL_OUT"
scp "$CMU_HOST:$BEST_REMOTE" "$LOCAL_OUT" 2>/dev/null || \
  scp "$CMU_HOST:$CMU_OUT_MODEL" "${LOCAL_OUT/_best/}" 2>/dev/null || \
  echo "Could not copy model — retrieve manually from $CMU_HOST:$CMU_OUT_MODEL"

echo ""
echo "Done. Add to .env (or set in GUI under HTR backends → Kraken HTR model):"
echo "  TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH=$LOCAL_OUT"
