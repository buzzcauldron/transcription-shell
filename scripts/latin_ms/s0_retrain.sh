#!/usr/bin/env bash
# Stage 0 — Retrain: fine-tune the Kraken segmentation model and the PyTorch
# U-Net lineation model on the combined ground truth dataset.
#
# "Update the old model" mode (default): loads the existing Kraken model and
# resumes/extends the U-Net from any existing checkpoint.
#
# GPU jobs (segtrain, ketos train) run SEQUENTIALLY to avoid OOM.
# U-Net (CPU/small GPU) runs in parallel with the second GPU job if available.
#
# Outputs land in $LATIN_MS_WORKSPACE/training/:
#   kraken_seg_updated_best.mlmodel  — drop-in for model_249.mlmodel
#   htr_latin_updated_best.mlmodel   — drop-in for Tridis_Medieval_EarlyModern.mlmodel
#   line_mask_unet.pt                — drop-in for TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH
#
# Usage:  s0_retrain.sh [--epochs N] [--device cpu|cuda|mps|auto] [--batch-size N]
#         s0_retrain.sh [--seg-only | --htr-only | --no-htr]
#         s0_retrain.sh [--lrate LR] [--preprocess-cucim]
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
BATCH_SIZE=1
LRATE=""
RUN_SEG=true
RUN_UNET=true
RUN_HTR=true
USE_CUCIM=false
BASELINE_ONLY=false
# HTR stability: previous run diverged to NaN at epoch 5 with default Adam@1e-3
# and --augment. New defaults: lower LR, cosine anneal, warmup, augment opt-in.
HTR_LRATE=0.0003
HTR_SCHEDULE=cosine
HTR_COS_MIN_LR=0.00005
HTR_WARMUP=100
HTR_AUGMENT=false
# Use `--quit fixed --epochs N` instead of early-stopping on val_loss because
# ketos's default monitor saves "best" at epoch 0 when fine-tuning from a
# strong base (loss stops moving after the first pass). Fixed-budget training
# lets the cosine schedule actually anneal; pick the trained checkpoint by
# external CER comparison (transcriber-shell htr-compare).
HTR_QUIT=fixed
# Stratified train/val files (preempts --partition skew on imbalanced GT).
HTR_TRAIN_FILES=""
HTR_VAL_FILES=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --epochs)           EPOCHS="$2"; shift 2 ;;
        --device)           DEVICE="$2"; shift 2 ;;
        --batch-size)       BATCH_SIZE="$2"; shift 2 ;;
        --lrate)            LRATE="$2"; shift 2 ;;
        --htr-lrate)        HTR_LRATE="$2"; shift 2 ;;
        --htr-schedule)     HTR_SCHEDULE="$2"; shift 2 ;;
        --htr-warmup)       HTR_WARMUP="$2"; shift 2 ;;
        --htr-augment)      HTR_AUGMENT=true; shift ;;
        --htr-quit)         HTR_QUIT="$2"; shift 2 ;;
        --htr-train-files)  HTR_TRAIN_FILES="$2"; shift 2 ;;
        --htr-val-files)    HTR_VAL_FILES="$2"; shift 2 ;;
        --seg-only)         RUN_UNET=false; RUN_HTR=false; shift ;;
        --htr-only)         RUN_SEG=false; RUN_UNET=false; shift ;;
        --no-htr)           RUN_HTR=false; shift ;;
        --preprocess-cucim) USE_CUCIM=true; shift ;;
        --baseline-only)    BASELINE_ONLY=true; shift ;;
        *) echo "Unknown: $1" >&2; exit 1 ;;
    esac
done

REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TRAIN_DIR="${LATIN_MS_WORKSPACE:-$HOME/latin-ms-workspace}/training"
COMBINED="${LATIN_MS_GT_DIR:-${TRAIN_DIR}/combined_gt}"
UNET_OUT="${TRAIN_DIR}/line_mask_unet.pt"
KRAKEN_BASE="${TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH:-/Users/halxiii/Projects/latin_documents-1/model_249.mlmodel}"
KRAKEN_OUT="${TRAIN_DIR}/kraken_seg_updated"
HTR_BASE="${TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH:-${TRAIN_DIR}/Tridis_Medieval_EarlyModern.mlmodel}"
HTR_OUT="${TRAIN_DIR}/htr_latin_updated"

mkdir -p "$TRAIN_DIR"

# ketos -d/--device is a GLOBAL flag on the parent `ketos` command — must come BEFORE subcommand.
# auto → cuda if available, else cpu.
KETOS_DEVICE_ARG=()
if [[ "$DEVICE" == "cuda" || "$DEVICE" == "gpu" ]]; then
    KETOS_DEVICE_ARG=(-d cuda:0)
elif [[ "$DEVICE" == "cpu" ]]; then
    KETOS_DEVICE_ARG=(-d cpu)
elif [[ "$DEVICE" == "mps" ]]; then
    KETOS_DEVICE_ARG=(-d mps)
elif [[ "$DEVICE" =~ ^cuda:[0-9]+$ ]]; then
    KETOS_DEVICE_ARG=(-d "$DEVICE")
# else "auto" — omit flag, ketos defaults to cpu
fi

echo "========================================================"
echo "  Stage 0: retrain lineation models"
echo "  Ground truth pairs: $(find "$COMBINED" -name '*.xml' | wc -l | tr -d ' ')"
echo "  Epochs: $EPOCHS  |  Device: $DEVICE  |  Batch: $BATCH_SIZE"
echo "========================================================"

# ── Optional cuCIM preprocessing ─────────────────────────────────────────────
# Resize training images on GPU before training to speed up augmentation.
# Only runs if --preprocess-cucim is set and cucim is installed.
if $USE_CUCIM; then
    CUCIM_OUT="${TRAIN_DIR}/combined_gt_cucim"
    echo ""
    echo "==> Preprocessing training images with cuCIM → ${CUCIM_OUT}"
    export CUCIM_SRC="$COMBINED"
    export CUCIM_DST="$CUCIM_OUT"
    python3 - <<'PYEOF'
import sys, os
try:
    import cucim.skimage.transform as cst
    import cupy as cp
    USE_GPU = True
except ImportError:
    USE_GPU = False

from pathlib import Path
from PIL import Image
import xml.etree.ElementTree as ET, shutil

src = Path(os.environ['CUCIM_SRC'])
dst = Path(os.environ['CUCIM_DST'])
dst.mkdir(parents=True, exist_ok=True)

MAX_DIM = 1800
done = skipped = 0
for xml in sorted(src.glob('*.xml')):
    for ext in ('.jpg', '.jpeg', '.png', '.tif', '.tiff'):
        img_src = xml.with_suffix(ext)
        if not img_src.exists():
            continue
        img_dst = dst / (img_src.stem + '.jpg')
        xml_dst = dst / xml.name
        if img_dst.exists() and xml_dst.exists():
            skipped += 1; break
        pil = Image.open(img_src)
        w, h = pil.size
        scale = min(MAX_DIM / max(w, h), 1.0)
        if scale < 1.0:
            nw, nh = int(w * scale), int(h * scale)
            if USE_GPU:
                import numpy as np
                arr = cp.asarray(np.array(pil.convert('RGB')))
                out = cst.resize(arr, (nh, nw, 3), anti_aliasing=True, preserve_range=True)
                Image.fromarray(cp.asnumpy(out).astype('uint8')).save(img_dst, quality=92, optimize=True)
            else:
                pil.resize((nw, nh), Image.LANCZOS).save(img_dst, quality=92, optimize=True)
            tree = ET.parse(str(xml))
            root = tree.getroot()
            pg = root.find('.//{*}Page')
            if pg is not None:
                pg.set('imageWidth', str(nw)); pg.set('imageHeight', str(nh))
                pg.set('imageFilename', str(img_dst))
            for el in root.iter():
                tag = el.tag.split('}')[-1]
                if tag in ('Coords', 'Baseline') and el.get('points'):
                    pts = []
                    for tok in el.get('points', '').split():
                        if ',' in tok:
                            x, _, y = tok.partition(',')
                            pts.append(f"{round(float(x)*scale)},{round(float(y)*scale)}")
                    el.set('points', ' '.join(pts))
            ns = root.tag.split('}')[0].lstrip('{') if '}' in root.tag else ''
            if ns:
                ET.register_namespace('', ns)
            tree.write(str(xml_dst), xml_declaration=True, encoding='unicode')
        else:
            shutil.copy2(img_src, img_dst)
            shutil.copy2(xml, xml_dst)
        done += 1; break

print(f"  cuCIM preprocessed {done} pairs, {skipped} already cached  (GPU={USE_GPU})")
PYEOF
    COMBINED="$CUCIM_OUT"
    echo "  Using preprocessed images from ${COMBINED}"
fi

GT_XMLS=("$COMBINED"/*.xml)

LRATE_ARG=()
[[ -n "$LRATE" ]] && LRATE_ARG=(-r "$LRATE")

# ── 1. Kraken segmentation fine-tune ─────────────────────────────────────────
# Runs first; owns the GPU until complete.
if $RUN_SEG; then
    echo ""
    echo "==> Kraken segtrain (fine-tune from ${KRAKEN_BASE##*/})..."
    SUPPRESS_ARG=()
    $BASELINE_ONLY && SUPPRESS_ARG=(--suppress-regions)
    $BASELINE_ONLY && echo "  (baseline-only mode: --suppress-regions)"
    ketos "${KETOS_DEVICE_ARG[@]}" segtrain \
        --load "$KRAKEN_BASE" \
        --resize union \
        --output "$KRAKEN_OUT" \
        --epochs "$EPOCHS" \
        --quit early \
        --lag 5 \
        --augment \
        "${SUPPRESS_ARG[@]}" \
        "${LRATE_ARG[@]}" \
        "${GT_XMLS[@]}" 2>&1 | tee "${TRAIN_DIR}/training_seg.log" | \
        grep --line-buffered -aE "epoch|loss|best|Saving|Error|OOM|Killed|stage [0-9]|early_stopp"
    echo "  segtrain done."
fi

# ── 2. Kraken HTR recognition fine-tune ──────────────────────────────────────
# Runs second; GPU is free after segtrain.
if $RUN_HTR; then
    if [[ ! -f "$HTR_BASE" ]]; then
        echo "  WARNING: HTR base model not found at ${HTR_BASE} — skipping ketos train"
    else
        echo ""
        echo "==> Kraken ketos train (HTR fine-tune from ${HTR_BASE##*/})..."
        # NaN guard rails: lower LR (0.0003 vs Adam default 0.001), cosine
        # anneal, warmup, no-augment by default. --htr-lrate / --htr-augment
        # can override. --lrate (global) still wins if set.
        HTR_AUGMENT_ARG=()
        $HTR_AUGMENT && HTR_AUGMENT_ARG=(--augment)
        HTR_LRATE_FINAL="${LRATE:-$HTR_LRATE}"
        # --quit fixed bypasses the loss-monitor early-stop pathology
        # (best=epoch 0 problem). With --lag still given, but for the chosen
        # quit mode only "fixed" or "early" matter; --lag is ignored for fixed.
        HTR_QUIT_ARGS=(--quit "$HTR_QUIT")
        [[ "$HTR_QUIT" == "early" ]] && HTR_QUIT_ARGS+=(--lag 5)
        # Stratified train/val files (preempts --partition source skew).
        HTR_FILE_ARGS=()
        if [[ -n "$HTR_TRAIN_FILES" && -n "$HTR_VAL_FILES" ]]; then
            HTR_FILE_ARGS=(-t "$HTR_TRAIN_FILES" -e "$HTR_VAL_FILES")
            HTR_GT_INPUT=()
            echo "  HTR: stratified split (train=$HTR_TRAIN_FILES, eval=$HTR_VAL_FILES)"
        else
            HTR_GT_INPUT=("${GT_XMLS[@]}")
        fi
        echo "  HTR: lrate=${HTR_LRATE_FINAL}  schedule=${HTR_SCHEDULE}  warmup=${HTR_WARMUP}  augment=${HTR_AUGMENT}  quit=${HTR_QUIT}"
        ketos "${KETOS_DEVICE_ARG[@]}" train \
            -f page \
            -i "$HTR_BASE" \
            --resize add \
            -o "$HTR_OUT" \
            --epochs "$EPOCHS" \
            "${HTR_QUIT_ARGS[@]}" \
            -r "$HTR_LRATE_FINAL" \
            --schedule "$HTR_SCHEDULE" \
            --cos-min-lr "$HTR_COS_MIN_LR" \
            --warmup "$HTR_WARMUP" \
            "${HTR_AUGMENT_ARG[@]}" \
            "${HTR_FILE_ARGS[@]}" \
            "${HTR_GT_INPUT[@]}" 2>&1 | tee "${TRAIN_DIR}/training_htr.log" | \
            grep --line-buffered -aE "epoch|loss|best|Saving|Error|CER|stage [0-9]|nan|NaN"
        echo "  ketos train done."
    fi
fi

# ── 3. PyTorch U-Net (latin_lineation_mvp) ────────────────────────────────────
# Runs last (or in background alongside HTR if latin-lineation-train exists).
if $RUN_UNET; then
    if ! command -v latin-lineation-train &>/dev/null; then
        echo "  WARNING: latin-lineation-train not found — skipping U-Net training"
    else
        echo ""
        echo "==> PyTorch U-Net train (latin_lineation_mvp)..."
        RESUME_FLAG=""
        [[ -f "${UNET_OUT%.pt}.train.pt" ]] && RESUME_FLAG="--resume auto"
        latin-lineation-train \
            --data-dir "$COMBINED" \
            --epochs "$EPOCHS" \
            --out "$UNET_OUT" \
            --device "$DEVICE" \
            $RESUME_FLAG 2>&1 | tee "${TRAIN_DIR}/training_unet.log" | \
            grep --line-buffered -aE "epoch|loss|val|best|saved|Error"
        echo "  U-Net train done."
    fi
fi

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
