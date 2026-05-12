#!/usr/bin/env bash
# Stage 0 — Retrain: fine-tune the Kraken segmentation model and the PyTorch
# U-Net lineation model on the combined ground truth dataset.
#
# "Update the old model" mode (default): loads the existing Kraken model and
# resumes/extends the U-Net from any existing checkpoint.
#
# Outputs land in $LATIN_MS_WORKSPACE/training/:
#   kraken_seg_updated_best.mlmodel  — drop-in for model_249.mlmodel
#   line_mask_unet.pt                — drop-in for TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH
#
# Usage:  s0_retrain.sh [--epochs N] [--device cpu|cuda|mps|auto]
#
# After training:
#   Set TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH=$LATIN_MS_WORKSPACE/training/kraken_seg_updated_best.mlmodel
#   Set TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH=$LATIN_MS_WORKSPACE/training/line_mask_unet.pt
# in .env.latin-ms, then rerun stage 3.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

EPOCHS=30
DEVICE=auto

while [[ $# -gt 0 ]]; do
    case "$1" in
        --epochs) EPOCHS="$2"; shift 2 ;;
        --device) DEVICE="$2"; shift 2 ;;
        *) echo "Unknown: $1" >&2; exit 1 ;;
    esac
done

REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TRAIN_DIR="${LATIN_MS_WORKSPACE:-$HOME/latin-ms-workspace}/training"
COMBINED="${TRAIN_DIR}/combined_gt"
UNET_OUT="${TRAIN_DIR}/line_mask_unet.pt"
# Default to the model_249.mlmodel next to the repo's latin_documents data,
# or fall through to any path set in the env.
REPO_MODEL="${REPO_ROOT}/examples/latin_lineation_mvp/../../../latin_documents-1/model_249.mlmodel"
KRAKEN_BASE="${TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH:-/Users/halxiii/Projects/latin_documents-1/model_249.mlmodel}"
KRAKEN_OUT="${TRAIN_DIR}/kraken_seg_updated"

mkdir -p "$TRAIN_DIR"

echo "========================================================"
echo "  Stage 0: retrain lineation models"
echo "  Ground truth pairs: $(find "$COMBINED" -name '*.xml' | wc -l | tr -d ' ')"
echo "  Epochs: $EPOCHS  |  Device: $DEVICE"
echo "========================================================"

# ── 1. Kraken segmentation fine-tune ─────────────────────────────────────────
echo ""
echo "==> Kraken segtrain (fine-tune from ${KRAKEN_BASE##*/})..."
GT_XMLS=("$COMBINED"/*.xml)
ketos segtrain \
    --load "$KRAKEN_BASE" \
    --resize union \
    --output "$KRAKEN_OUT" \
    --epochs "$EPOCHS" \
    --quit early \
    --lag 5 \
    "${GT_XMLS[@]}" \
    2>&1 | grep -E "epoch|loss|best|Saving|Error" | head -80 &
KRAKEN_PID=$!

# ── 2. PyTorch U-Net (latin_lineation_mvp) ────────────────────────────────────
echo "==> PyTorch U-Net train (latin_lineation_mvp)..."
RESUME_FLAG=""
[[ -f "${UNET_OUT%.pt}.train.pt" ]] && RESUME_FLAG="--resume auto"

latin-lineation-train \
    --data-dir "$COMBINED" \
    --epochs "$EPOCHS" \
    --out "$UNET_OUT" \
    --device "$DEVICE" \
    $RESUME_FLAG \
    2>&1 | grep -E "epoch|loss|val|best|saved|Error" | head -80 &
UNET_PID=$!

echo "  Kraken PID: $KRAKEN_PID  |  U-Net PID: $UNET_PID"
echo "  Training in background — tail logs with:"
echo "    ps aux | grep -E 'ketos|latin-lineation'"

wait $KRAKEN_PID || echo "  Kraken segtrain exited (check above for errors)"
wait $UNET_PID   || echo "  U-Net train exited (check above for errors)"

echo ""
echo "========================================================"
echo "  Training done."
KRAKEN_BEST=$(find "$TRAIN_DIR" -name "kraken_seg_updated_best.mlmodel" 2>/dev/null | head -1)
[[ -f "${KRAKEN_BEST:-}" ]] && echo "  Kraken model: $KRAKEN_BEST"
[[ -f "$UNET_OUT" ]]        && echo "  U-Net model:  $UNET_OUT"
echo ""
echo "  Wire into pipeline — add to .env.latin-ms:"
echo "    TRANSCRIBER_SHELL_LINEATION_BACKEND=kraken"
echo "    TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH=${KRAKEN_BEST:-${KRAKEN_OUT}_best.mlmodel}"
echo "  or:"
echo "    TRANSCRIBER_SHELL_LINEATION_BACKEND=mask"
echo "    TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE=latin_lineation_mvp.infer:predict_masks"
echo "    TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH=${UNET_OUT}"
echo "========================================================"
