#!/usr/bin/env bash
# Poll CMU until ketos training finishes, then copy the best model locally.
#
# Usage:
#   export CMU_HOST=seth@akdeniz.lan.cmu.edu
#   ./scripts/wait_and_copy_htr_model.sh
#
# Options (env vars):
#   CMU_HOST        SSH target (required)
#   CMU_LOG         Remote train log path (default: ~/src/train.log)
#   CMU_MODEL       Remote model prefix (default: ~/src/gm-hf-htr)
#   LOCAL_OUT_DIR   Where to put the model locally (default: ~/src)
#   POLL_SECONDS    How often to check (default: 120)

set -euo pipefail

: "${CMU_HOST:?Set CMU_HOST to user@host.andrew.cmu.edu}"
CMU_LOG="${CMU_LOG:-~/src/train.log}"
CMU_MODEL="${CMU_MODEL:-~/src/gm-hf-htr}"
LOCAL_OUT_DIR="${LOCAL_OUT_DIR:-$HOME/src}"
POLL_SECONDS="${POLL_SECONDS:-120}"

BEST_REMOTE="${CMU_MODEL%.mlmodel}_best.mlmodel"

echo "Watching $CMU_HOST:$CMU_LOG for training completion…"
echo "(polling every ${POLL_SECONDS}s)"
echo ""

while true; do
    # Training is done when ketos process is gone OR log ends with "Training complete" / "EarlyStopping"
    DONE=$(ssh "$CMU_HOST" bash <<'REMOTE'
        log=~/src/train.log
        if ! pgrep -f "ketos.*train" > /dev/null 2>&1; then
            echo "process_gone"
        elif grep -q "Training complete\|EarlyStopping\|Epoch.*stopped" "$log" 2>/dev/null; then
            echo "log_done"
        else
            echo "running"
        fi
REMOTE
)

    if [[ "$DONE" != "running" ]]; then
        echo "Training finished ($DONE). Copying model…"
        break
    fi

    # Show current best accuracy
    BEST=$(ssh "$CMU_HOST" "grep -a '0/[0-9]' ~/src/train.log 2>/dev/null | tail -1 | grep -oP '0\.[0-9]+' | head -1" 2>/dev/null || echo "?")
    echo "$(date '+%H:%M:%S')  still training — current best val_accuracy: $BEST"
    sleep "$POLL_SECONDS"
done

# Copy best model (fall back to final checkpoint)
LOCAL_BEST="$LOCAL_OUT_DIR/$(basename "$BEST_REMOTE")"
echo ""
if scp "$CMU_HOST:$BEST_REMOTE" "$LOCAL_BEST" 2>/dev/null; then
    echo "Copied: $LOCAL_BEST"
else
    FINAL="${CMU_MODEL}.mlmodel"
    LOCAL_FINAL="$LOCAL_OUT_DIR/$(basename "$FINAL")"
    scp "$CMU_HOST:$FINAL" "$LOCAL_FINAL"
    echo "Copied final checkpoint: $LOCAL_FINAL"
    LOCAL_BEST="$LOCAL_FINAL"
fi

echo ""
echo "Model ready. Set in .env or GUI (HTR backends → Kraken HTR model):"
echo "  TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH=$LOCAL_BEST"
