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
LRATE=""
RUN_SEG=true
RUN_UNET=true
RUN_HTR=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --epochs)   EPOCHS="$2"; shift 2 ;;
        --device)   DEVICE="$2"; shift 2 ;;
        --lrate)    LRATE="$2"; shift 2 ;;
        --seg-only) RUN_UNET=false; RUN_HTR=false; shift ;;
        --htr-only) RUN_SEG=false; RUN_UNET=false; shift ;;
        --no-htr)   RUN_HTR=false; shift ;;
        *) echo "Unknown: $1" >&2; exit 1 ;;
    esac
done

REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TRAIN_DIR="${LATIN_MS_WORKSPACE:-$HOME/latin-ms-workspace}/training"
COMBINED="${LATIN_MS_GT_DIR:-${TRAIN_DIR}/combined_gt}"
UNET_OUT="${TRAIN_DIR}/line_mask_unet.pt"
# Default to the model_249.mlmodel next to the repo's latin_documents data,
# or fall through to any path set in the env.
REPO_MODEL="${REPO_ROOT}/examples/latin_lineation_mvp/../../../latin_documents-1/model_249.mlmodel"
KRAKEN_BASE="${TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH:-/Users/halxiii/Projects/latin_documents-1/model_249.mlmodel}"
KRAKEN_OUT="${TRAIN_DIR}/kraken_seg_updated"
HTR_BASE="${TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH:-${TRAIN_DIR}/Tridis_Medieval_EarlyModern.mlmodel}"
HTR_OUT="${TRAIN_DIR}/htr_latin_updated"

mkdir -p "$TRAIN_DIR"

echo "========================================================"
echo "  Stage 0: retrain lineation models"
echo "  Ground truth pairs: $(find "$COMBINED" -name '*.xml' | wc -l | tr -d ' ')"
echo "  Epochs: $EPOCHS  |  Device: $DEVICE"
echo "========================================================"

GT_XMLS=("$COMBINED"/*.xml)
PIDS=()

# ── 1. Kraken segmentation fine-tune ─────────────────────────────────────────
if $RUN_SEG; then
echo ""
echo "==> Kraken segtrain (fine-tune from ${KRAKEN_BASE##*/})..."
SEG_LRATE_ARG=()
[[ -n "$LRATE" ]] && SEG_LRATE_ARG=(-r "$LRATE")
ketos segtrain \
    --load "$KRAKEN_BASE" \
    --resize union \
    --output "$KRAKEN_OUT" \
    --epochs "$EPOCHS" \
    --quit early \
    --lag 5 \
    --augment \
    "${SEG_LRATE_ARG[@]}" \
    "${GT_XMLS[@]}" \
    2>&1 | grep -E "epoch|loss|best|Saving|Error" | head -200 &
PIDS+=($!)
fi

# ── 2. PyTorch U-Net (latin_lineation_mvp) ────────────────────────────────────
if $RUN_UNET; then
if ! command -v latin-lineation-train &>/dev/null; then
    echo "  WARNING: latin-lineation-train not found — skipping U-Net training"
else
echo "==> PyTorch U-Net train (latin_lineation_mvp)..."
RESUME_FLAG=""
[[ -f "${UNET_OUT%.pt}.train.pt" ]] && RESUME_FLAG="--resume auto"

latin-lineation-train \
    --data-dir "$COMBINED" \
    --epochs "$EPOCHS" \
    --out "$UNET_OUT" \
    --device "$DEVICE" \
    $RESUME_FLAG \
    2>&1 | grep -E "epoch|loss|val|best|saved|Error" | head -200 &
PIDS+=($!)
fi
fi

# ── 3. Kraken HTR recognition fine-tune ──────────────────────────────────────
if $RUN_HTR; then
if [[ ! -f "$HTR_BASE" ]]; then
    echo "  WARNING: HTR base model not found at ${HTR_BASE} — skipping ketos train"
else
echo "==> Kraken ketos train (HTR fine-tune from ${HTR_BASE##*/})..."
HTR_LRATE_ARG=()
[[ -n "$LRATE" ]] && HTR_LRATE_ARG=(-r "$LRATE")
ketos train \
    -f page \
    -i "$HTR_BASE" \
    --resize add \
    -o "$HTR_OUT" \
    --epochs "$EPOCHS" \
    --quit early \
    --lag 5 \
    --augment \
    "${HTR_LRATE_ARG[@]}" \
    "${GT_XMLS[@]}" \
    2>&1 | grep -E "epoch|loss|best|Saving|Error|CER" | head -200 &
PIDS+=($!)
fi
fi

echo ""
echo "  PIDs: ${PIDS[*]:-none}"
echo "  Training in background — tail logs with:"
echo "    ps aux | grep -E 'ketos|latin-lineation'"

for pid in "${PIDS[@]}"; do
    wait "$pid" || echo "  Job PID $pid exited (check above for errors)"
done

echo ""
echo "========================================================"
echo "  Training done."
KRAKEN_BEST=$(find "$TRAIN_DIR" -name "kraken_seg_updated_best.mlmodel" 2>/dev/null | head -1)
HTR_BEST=$(find "$TRAIN_DIR" -name "htr_latin_updated_best.mlmodel" 2>/dev/null | head -1)
[[ -f "${KRAKEN_BEST:-}" ]] && echo "  Kraken seg model: $KRAKEN_BEST"
[[ -f "$UNET_OUT" ]]        && echo "  U-Net model:      $UNET_OUT"
[[ -f "${HTR_BEST:-}" ]]    && echo "  HTR model:        $HTR_BEST"
echo ""
echo "  Wire into pipeline — add to .env.latin-ms:"
echo "    TRANSCRIBER_SHELL_LINEATION_BACKEND=kraken"
echo "    TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH=${KRAKEN_BEST:-${KRAKEN_OUT}_best.mlmodel}"
[[ -f "${HTR_BEST:-}" ]] && \
echo "    TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH=${HTR_BEST}"
echo "  or (U-Net lineation):"
echo "    TRANSCRIBER_SHELL_LINEATION_BACKEND=mask"
echo "    TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE=latin_lineation_mvp.infer:predict_masks"
echo "    TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH=${UNET_OUT}"
echo "========================================================"
