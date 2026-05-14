#!/usr/bin/env bash
# Post-training: wait for the CMU HTR run to finish, sync the new model,
# materialize the stratified val set locally, then run htr-compare against
# Tridis. Reports per-page Δ CER so we know whether to keep the fine-tune.
#
# Usage:
#   bash scripts/latin_ms/htr_postrun_compare.sh                 # poll + run
#   bash scripts/latin_ms/htr_postrun_compare.sh --no-wait       # skip polling
#   bash scripts/latin_ms/htr_postrun_compare.sh --poll-secs 60  # tweak cadence
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

SERVER="seth@akdeniz.lan.cmu.edu"
REMOTE_TRAIN_DIR="~/latin-ms-workspace/training"
REMOTE_LOG="${REMOTE_TRAIN_DIR}/training_htr_v3.log"
LOCAL_TRAIN_DIR="${HOME}/latin-ms-workspace/training"
LOCAL_GT_DIR="${LOCAL_TRAIN_DIR}/combined_gt"
LOCAL_VAL_GT_DIR="${LOCAL_TRAIN_DIR}/val_holdout_gt"
TRIDIS_MODEL="${LOCAL_TRAIN_DIR}/Tridis_Medieval_EarlyModern.mlmodel"
NEW_MODEL="${LOCAL_TRAIN_DIR}/htr_latin_updated_best.mlmodel"
REPORT_OUT="${LOCAL_TRAIN_DIR}/htr_compare_report.txt"

WAIT=true
POLL_SECS=60
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-wait)     WAIT=false; shift ;;
        --poll-secs)   POLL_SECS="$2"; shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

echo "===================================================="
echo " HTR post-run comparison"
echo " Server : ${SERVER}"
echo " Tridis : ${TRIDIS_MODEL##*/}"
echo " Report : ${REPORT_OUT}"
echo "===================================================="

# ── 1. Wait for training completion ──────────────────────────────────────────
if $WAIT; then
    echo ""
    echo "==> Polling for TRAINING_DONE marker (every ${POLL_SECS}s)..."
    while true; do
        if ssh "$SERVER" "tail -3 ${REMOTE_LOG} 2>/dev/null | grep -q TRAINING_DONE"; then
            echo "  training complete."
            break
        fi
        # Also exit if no ketos process is alive (covers manual kill / crash).
        if ! ssh "$SERVER" "pgrep -f 'ketos.*train' >/dev/null 2>&1"; then
            echo "  no ketos process running — assuming done or killed."
            break
        fi
        STAGE=$(ssh "$SERVER" "tmux capture-pane -t train -p 2>/dev/null | grep -aoE 'stage [0-9]+/[0-9]+' | tail -1" 2>/dev/null || true)
        printf "  waiting...  %s\n" "${STAGE:-<no stage info>}"
        sleep "$POLL_SECS"
    done
fi

# ── 2. Sync new HTR model ────────────────────────────────────────────────────
echo ""
echo "==> Syncing htr_latin_updated_best.mlmodel..."
rsync -avz "${SERVER}:${REMOTE_TRAIN_DIR}/htr_latin_updated_best.mlmodel" \
    "${LOCAL_TRAIN_DIR}/" 2>&1 | tail -3
if [[ ! -f "$NEW_MODEL" ]]; then
    echo "ERROR: new HTR model not found at ${NEW_MODEL}" >&2
    exit 1
fi

# ── 3. Materialize val holdout GT locally ────────────────────────────────────
# Read the val_files.txt list (server paths), rewrite to local paths, copy
# matching XMLs and images into LOCAL_VAL_GT_DIR.
echo ""
echo "==> Materializing val holdout GT at ${LOCAL_VAL_GT_DIR}..."
mkdir -p "$LOCAL_VAL_GT_DIR"
TMP_VAL="$(mktemp)"
ssh "$SERVER" "cat ${REMOTE_TRAIN_DIR}/val_files.txt" > "$TMP_VAL"
N_VAL=0
while IFS= read -r REMOTE_XML; do
    [[ -z "$REMOTE_XML" ]] && continue
    STEM=$(basename "$REMOTE_XML" .xml)
    # Find the local XML (combined_gt mirrors server, modulo path prefix)
    LOCAL_XML="${LOCAL_GT_DIR}/${STEM}.xml"
    if [[ -f "$LOCAL_XML" ]]; then
        cp "$LOCAL_XML" "$LOCAL_VAL_GT_DIR/"
        for EXT in .jpg .jpeg .png .tif .tiff; do
            if [[ -f "${LOCAL_GT_DIR}/${STEM}${EXT}" ]]; then
                cp "${LOCAL_GT_DIR}/${STEM}${EXT}" "$LOCAL_VAL_GT_DIR/"
                break
            fi
        done
        N_VAL=$((N_VAL + 1))
    else
        echo "  warning: ${STEM}.xml not found locally — skipping" >&2
    fi
done < "$TMP_VAL"
rm -f "$TMP_VAL"
echo "  ${N_VAL} val pages staged."

# ── 4. Run htr-compare ───────────────────────────────────────────────────────
echo ""
echo "==> Running htr-compare (CPU)..."
echo ""
transcriber-shell htr-compare \
    "$TRIDIS_MODEL" \
    "$NEW_MODEL" \
    "$LOCAL_VAL_GT_DIR" \
    --device cpu \
    | tee "$REPORT_OUT"

echo ""
echo "===================================================="
echo " Report written to: ${REPORT_OUT}"
echo "===================================================="
echo ""
echo " If candidate wins clearly (mean Δ CER < -0.5%), wire into .env.latin-ms:"
echo "   sed -i '' 's|^# TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH=|TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH=|' \\"
echo "       ${ENV_FILE}"
