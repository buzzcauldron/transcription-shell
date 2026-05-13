#!/usr/bin/env bash
# setup_server.sh — Provision CMU training server and launch HTR/seg fine-tuning.
#
# Rsyncs training data, installs Kraken, creates workspace, then starts
# s0_retrain.sh inside a tmux session so training survives SSH disconnect.
#
# Prerequisites (local):
#   - SSH access: seth@akdeniz.lan.cmu.edu (key-based preferred)
#   - ~/latin-ms-workspace/training/combined_gt/ populated
#   - ~/latin-ms-workspace/training/Tridis_Medieval_EarlyModern.mlmodel present
#
# Usage:
#   bash setup_server.sh [--epochs N] [--htr-only] [--seg-only] [--dry-run]
set -euo pipefail

SERVER="seth@akdeniz.lan.cmu.edu"
REMOTE_WS="~/latin-ms-workspace"
LOCAL_TRAIN="$HOME/latin-ms-workspace/training"
LOCAL_SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${LOCAL_SCRIPTS}/../.." && pwd)"

EPOCHS=50
TRAIN_FLAGS=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --epochs)   EPOCHS="$2"; TRAIN_FLAGS+=" --epochs $2"; shift 2 ;;
        --htr-only) TRAIN_FLAGS+=" --htr-only"; shift ;;
        --seg-only) TRAIN_FLAGS+=" --seg-only"; shift ;;
        --no-htr)   TRAIN_FLAGS+=" --no-htr"; shift ;;
        --dry-run)  DRY_RUN=true; shift ;;
        *) echo "Unknown: $1" >&2; exit 1 ;;
    esac
done

RSYNC="rsync -avz --progress"
$DRY_RUN && RSYNC="rsync -avzn --progress"

echo "========================================================"
echo "  setup_server.sh"
echo "  Server:  ${SERVER}"
echo "  Epochs:  ${EPOCHS}"
echo "  Flags:   ${TRAIN_FLAGS:-default (seg + unet + htr)}"
$DRY_RUN && echo "  [DRY RUN]"
echo "========================================================"

# ── 1. Create remote workspace ────────────────────────────────────────────────
echo ""
echo "==> Creating remote workspace..."
ssh "$SERVER" "mkdir -p ${REMOTE_WS}/training/combined_gt ${REMOTE_WS}/scripts/latin_ms"

# ── 2. Rsync training data ────────────────────────────────────────────────────
echo "==> Syncing combined_gt (images + XMLs)..."
$RSYNC \
    "${LOCAL_TRAIN}/combined_gt/" \
    "${SERVER}:${REMOTE_WS}/training/combined_gt/"

echo "==> Syncing base models..."
for f in \
    "${LOCAL_TRAIN}/Tridis_Medieval_EarlyModern.mlmodel" \
    "$HOME/Projects/latin_documents-1/model_249.mlmodel"
do
    [[ -f "$f" ]] && $RSYNC "$f" "${SERVER}:${REMOTE_WS}/training/" || \
        echo "  WARNING: ${f##*/} not found locally, skipping"
done

# ── 3. Rsync scripts ──────────────────────────────────────────────────────────
echo "==> Syncing scripts..."
$RSYNC \
    --exclude='.env.latin-ms' \
    --exclude='__pycache__/' \
    "${LOCAL_SCRIPTS}/" \
    "${SERVER}:${REMOTE_WS}/scripts/latin_ms/"

# ── 4. Create venv + install Kraken on server ────────────────────────────────
VENV_PATH="${REMOTE_WS}/venv"
echo "==> Setting up Python venv at ${VENV_PATH}..."
ssh "$SERVER" "
set -e
VENV=${REMOTE_WS}/venv
if [[ ! -d \"\$VENV\" ]]; then
    echo '  Creating venv...'
    python3 -m venv \"\$VENV\"
fi
source \"\$VENV/bin/activate\"
if python3 -c 'import kraken' 2>/dev/null; then
    echo '  Kraken already installed in venv.'
else
    echo '  Installing Kraken (this may take a few minutes)...'
    pip install --quiet 'kraken' 2>&1 | tail -4
    echo '  Kraken installed.'
fi
python3 -c 'import kraken; print(\"  Kraken version:\", kraken.__version__)'
"

# ── 5. Write .env.latin-ms on server ─────────────────────────────────────────
echo "==> Writing .env.latin-ms on server..."
if ! $DRY_RUN; then
ssh "$SERVER" "cat > ${REMOTE_WS}/scripts/latin_ms/.env.latin-ms" <<EOF
LATIN_MS_WORKSPACE=${REMOTE_WS}
LATIN_MS_JOB_ID=server_train
LATIN_MS_GT_DIR=${REMOTE_WS}/training/combined_gt
TRANSCRIBER_SHELL_LINEATION_BACKEND=kraken
TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH=${REMOTE_WS}/training/model_249.mlmodel
TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH=${REMOTE_WS}/training/Tridis_Medieval_EarlyModern.mlmodel
EXPAND_DIPLOMATIC_MODEL=gemini-2.5-flash
MAGIC_ELISE_ROOT=${REMOTE_WS}/magic-elise-tool
EOF
fi

# ── 6. Launch training in tmux ────────────────────────────────────────────────
if $DRY_RUN; then
    echo ""
    echo "==> [DRY RUN] Would launch training in tmux session 'train' on ${SERVER}"
    echo "    Command: bash ${REMOTE_WS}/scripts/latin_ms/s0_retrain.sh --device cuda${TRAIN_FLAGS}"
    exit 0
fi

echo ""
echo "==> Launching training in tmux session 'train'..."
# Kill existing session if present to start fresh
ssh "$SERVER" "tmux kill-session -t train 2>/dev/null || true"
ssh "$SERVER" "tmux new-session -d -s train \
    'source ${REMOTE_WS}/venv/bin/activate && \
     cd ${REMOTE_WS} && \
     bash scripts/latin_ms/s0_retrain.sh --device cuda${TRAIN_FLAGS} \
     2>&1 | tee training.log; echo TRAINING_DONE; read'"

echo ""
echo "========================================================"
echo "  Training launched on ${SERVER}"
echo ""
echo "  Monitor:"
echo "    ssh ${SERVER} 'tmux attach -t train'"
echo "    ssh ${SERVER} 'tail -f ${REMOTE_WS}/training.log'"
echo ""
echo "  When done, sync models back:"
echo "    rsync -avz ${SERVER}:${REMOTE_WS}/training/htr_latin_updated_best.mlmodel \\"
echo "        ~/latin-ms-workspace/training/"
echo "    rsync -avz ${SERVER}:${REMOTE_WS}/training/kraken_seg_updated_best.mlmodel \\"
echo "        ~/latin-ms-workspace/training/"
echo "========================================================"
