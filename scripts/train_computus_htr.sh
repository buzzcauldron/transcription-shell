#!/usr/bin/env bash
# Launch a Carolingian/computus HTR fine-tune on halxvi (RTX 3080, 9.64 GB VRAM).
#
# Prereqs:
#   1. Run prepare_computus_htr_train.py to build manifests in GT_DIR.
#   2. Have the r2 base model available (see BASE_MODEL fallback logic below).
#   3. A ketos venv activated, or ketos on PATH.
#
# Usage (on halxvi, outside an existing tmux session):
#   bash scripts/train_computus_htr.sh
#
# Or launch detached immediately:
#   TRAIN_SESSION=computus-train bash scripts/train_computus_htr.sh
#
# Env-overridable knobs (see defaults below):
#   ROUND_LABEL    Label for this branch (default: c1)
#   GT_DIR         Directory containing train/val manifests
#   BASE_MODEL     Path to fine-tune base; falls back to son-of-gm-r2.mlmodel
#   OUT_MODEL      Output model prefix (without .mlmodel extension)
#   DEVICE         PyTorch device string (default: cuda:0)
#   WORKERS        DataLoader workers (default: 4)
#   BATCH_SIZE     Mini-batch size; 8 is safe on the 3080 (default: 8)
#   EPOCHS         Max epochs (default: 100)
#   LRATE          Learning rate (default: 0.00001)
#   LAG            Early-stopping patience in epochs (default: 20)
#   PRECISION      PyTorch Lightning precision (default: bf16-mixed)
#   SCHEDULE       LR schedule (default: cosine)
#   TRAIN_SESSION  tmux session name (default: computus-train)
#   LOG_DIR        Directory for log files (default: /home/sethj/disk3/training_logs)

set -euo pipefail

# ── Knob defaults ─────────────────────────────────────────────────────────────

ROUND_LABEL="${ROUND_LABEL:-c1}"
GT_DIR="${GT_DIR:-/home/sethj/disk3/computus-gt}"
OUT_MODEL="${OUT_MODEL:-/home/sethj/disk3/gm-htr-computus}"
DEVICE="${DEVICE:-cuda:0}"
WORKERS="${WORKERS:-4}"
BATCH_SIZE="${BATCH_SIZE:-8}"
EPOCHS="${EPOCHS:-100}"
LRATE="${LRATE:-0.00001}"
LAG="${LAG:-20}"
PRECISION="${PRECISION:-bf16-mixed}"
SCHEDULE="${SCHEDULE:-cosine}"
TRAIN_SESSION="${TRAIN_SESSION:-computus-train}"
LOG_DIR="${LOG_DIR:-/home/sethj/disk3/training_logs}"

# Base model: prefer the local r2 best, fall back to shared copy on disk3
_DEFAULT_BASE="$HOME/src/latin_documents/gm-htr-r2.mlmodel_best.mlmodel"
_FALLBACK_BASE="/home/sethj/disk3/models/son-of-gm-r2.mlmodel"
if [[ -n "${BASE_MODEL:-}" ]]; then
    : # caller-supplied; use as-is
elif [[ -f "$_DEFAULT_BASE" ]]; then
    BASE_MODEL="$_DEFAULT_BASE"
elif [[ -f "$_FALLBACK_BASE" ]]; then
    BASE_MODEL="$_FALLBACK_BASE"
    echo "WARN: primary base model not found; using fallback: $BASE_MODEL"
else
    echo "ERROR: no base model found at:"
    echo "  $_DEFAULT_BASE"
    echo "  $_FALLBACK_BASE"
    echo "Set BASE_MODEL= to override."
    exit 1
fi

# ── Derived paths ─────────────────────────────────────────────────────────────

TRAIN_MANIFEST="$GT_DIR/train_manifest.txt"
VAL_MANIFEST="$GT_DIR/val_manifest.txt"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/computus-${ROUND_LABEL}-$(date +%Y%m%d-%H%M%S).log"

# ── PyTorch allocator ─────────────────────────────────────────────────────────

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# ── Banner ────────────────────────────────────────────────────────────────────

echo "=== Computus HTR fine-tune — round ${ROUND_LABEL} ==="
echo "  Base model:  $BASE_MODEL"
echo "  GT dir:      $GT_DIR"
echo "  Output:      $OUT_MODEL"
echo "  Device:      $DEVICE   precision: $PRECISION"
echo "  Batch:       $BATCH_SIZE   workers: $WORKERS"
echo "  Epochs:      $EPOCHS   lag: $LAG   lr: $LRATE   sched: $SCHEDULE"
echo "  tmux session: $TRAIN_SESSION"
echo "  Log:         $LOG_FILE"
echo ""

# ── Guard: manifests exist and are large enough ───────────────────────────────

MIN_LINES=500

if [[ ! -f "$TRAIN_MANIFEST" ]]; then
    echo "ERROR: train manifest not found: $TRAIN_MANIFEST"
    echo "Run: python scripts/prepare_computus_htr_train.py --out-dir $GT_DIR"
    exit 1
fi
if [[ ! -f "$VAL_MANIFEST" ]]; then
    echo "ERROR: val manifest not found: $VAL_MANIFEST"
    echo "Run: python scripts/prepare_computus_htr_train.py --out-dir $GT_DIR"
    exit 1
fi

train_count=$(wc -l < "$TRAIN_MANIFEST")
val_count=$(wc -l < "$VAL_MANIFEST")
echo "Manifest sizes:  train=${train_count}  val=${val_count}"

if [[ "$train_count" -lt "$MIN_LINES" ]]; then
    echo "ERROR: train manifest has only ${train_count} lines; need at least ${MIN_LINES}."
    exit 1
fi

# ── Guard: base model ─────────────────────────────────────────────────────────

if [[ ! -f "$BASE_MODEL" ]]; then
    echo "ERROR: base model not found: $BASE_MODEL"
    exit 1
fi

# ── Warn: GPU free memory ─────────────────────────────────────────────────────

if command -v nvidia-smi &>/dev/null; then
    free_mb=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
    if [[ -n "$free_mb" && "$free_mb" -lt 7000 ]]; then
        echo "WARN: only ${free_mb} MiB GPU memory free (< 7 GB). Training may OOM."
        echo "      Kill other GPU processes before continuing."
        echo ""
    else
        echo "GPU free memory: ${free_mb:-unknown} MiB — OK"
    fi
else
    echo "WARN: nvidia-smi not found; cannot check GPU memory."
fi

# ── Guard: no existing tmux session ──────────────────────────────────────────

if tmux has-session -t "$TRAIN_SESSION" 2>/dev/null; then
    echo "ERROR: tmux session '$TRAIN_SESSION' already exists."
    echo "  Attach:  tmux attach -t $TRAIN_SESSION"
    echo "  Kill:    tmux kill-session -t $TRAIN_SESSION"
    exit 1
fi

# ── Launch in tmux ────────────────────────────────────────────────────────────

echo ""
echo "Launching ketos in tmux session '$TRAIN_SESSION'..."

tmux new-session -d -s "$TRAIN_SESSION" bash -c "
ketos \
  -d ${DEVICE} \
  --workers ${WORKERS} \
  --precision ${PRECISION} \
  train \
    -i '${BASE_MODEL}' \
    --resize union \
    -f page \
    -q early \
    --lag ${LAG} \
    --min-epochs 5 \
    -N ${EPOCHS} \
    -B ${BATCH_SIZE} \
    -r ${LRATE} \
    --schedule ${SCHEDULE} \
    --augment \
    -t '${TRAIN_MANIFEST}' \
    -e '${VAL_MANIFEST}' \
    -o '${OUT_MODEL}' \
  2>&1 | tee '${LOG_FILE}'
echo ''
echo '=== Training session ended: \$(date) ==='
echo 'Press any key to close this pane...'
read -n1
"

# ── Post-launch instructions ──────────────────────────────────────────────────

echo ""
echo "Session launched.  Useful commands:"
echo ""
echo "  Attach to session:"
echo "    tmux attach -t $TRAIN_SESSION"
echo ""
echo "  Watch log from outside tmux:"
echo "    tail -f $LOG_FILE"
echo ""
echo "  Best model will be written to:"
echo "    ${OUT_MODEL}_best.mlmodel"
echo ""
echo "─────────────────────────────────────────────────────────────────"
echo "  When training completes, copy the best model:"
echo ""
echo "  1. To akdeniz (CMU):"
echo "    rsync -avz --progress \\"
echo "      '${OUT_MODEL}_best.mlmodel' \\"
echo "      sethj@akdeniz.andrew.cmu.edu:/home/sethj/src/models/gm-htr-computus-${ROUND_LABEL}_best.mlmodel"
echo ""
echo "  2. To this Mac:"
echo "    rsync -avz --progress \\"
echo "      sethj@halxvi.local:'${OUT_MODEL}_best.mlmodel' \\"
echo "      ~/src/models/gm-htr-computus-${ROUND_LABEL}_best.mlmodel"
echo "─────────────────────────────────────────────────────────────────"
