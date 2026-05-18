#!/usr/bin/env bash
# Poll server for training completion, rsync models to Disk3, update .env.
#
# Watches three jobs:
#   merge-seg    → kraken-merged-seg.mlmodel_best.mlmodel  → KRAKEN_MODEL_PATH
#   r2-train     → gm-htr-r2.mlmodel_best.mlmodel          → KRAKEN_HTR_MODEL_PATH
#   r3-train     → gm-htr-r3.mlmodel_best.mlmodel          → KRAKEN_HTR_MODEL_PATH
#   son-of-gm    → son-of-gm.mlmodel_best.mlmodel          → KRAKEN_HTR_MODEL_PATH (final)
#
# Usage: bash scripts/watch_training.sh

set -euo pipefail

SERVER="seth@akdeniz.lan.cmu.edu"
SSH="ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3"
DISK3="/home/sethj/disk3/models"
ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$DISK3"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

update_env() {
    local key="$1" val="$2"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    else
        echo "${key}=${val}" >> "$ENV_FILE"
    fi
    log "Updated .env: ${key}=${val}"
}

fetch_model() {
    local remote_path="$1" local_name="$2"
    local dest="$DISK3/$local_name"
    log "Rsyncing $remote_path → $dest" >&2
    rsync -az --progress "$SERVER:$remote_path" "$dest" >&2
    echo "$dest"
}

commit_env() {
    local model_name="$1"
    cd "$REPO"
    git add -f .env 2>/dev/null || true
    git diff --cached --quiet && return 0
    git commit -m "chore: update model path to ${model_name} after training" 2>/dev/null || true
    log "Committed .env update (or skipped if ignored)"
}

SEG_DONE=0
HTR_DONE=0
SOG_DONE=0

log "Watching for training completion on $SERVER …"
log "  merge-seg  → $DISK3/kraken-merged-seg.mlmodel"
log "  r2-train   → $DISK3/son-of-gm-r2.mlmodel"
log "  r3-train   → $DISK3/son-of-gm-r3.mlmodel"
log "  son-of-gm  → $DISK3/son-of-gm.mlmodel"
log "Polling every 5 minutes. Ctrl-C to stop."
echo ""

while true; do
    # ── merge-seg ──────────────────────────────────────────────────────
    if [[ "$SEG_DONE" -eq 0 ]]; then
        # Done when no ketos process for merge-seg AND best model exists
        seg_proc=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "pgrep -f 'keto[s].*kraken-merged-seg' 2>/dev/null | head -1" 2>/dev/null || true)
        seg_model=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "ls ~/src/kraken-merged-seg.mlmodel_best.mlmodel 2>/dev/null" 2>/dev/null || true)
        if [[ -z "$seg_proc" && -n "$seg_model" ]]; then
            log "merge-seg DONE — best model: $seg_model"
            dest=$(fetch_model "$seg_model" "kraken-merged-seg.mlmodel")
            update_env "TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH" "$dest"
            commit_env "kraken-merged-seg"
            SEG_DONE=1
        else
            progress=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "grep -oP 'stage \K[0-9]+/∞' \$(ls -t ~/merge-seg-*.log 2>/dev/null | head -1) 2>/dev/null | tail -1" 2>/dev/null || true)
            val=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "grep -oP 'val_mean_iu:\s*\K[0-9.]+' \$(ls -t ~/merge-seg-*.log 2>/dev/null | head -1) 2>/dev/null | tail -1" 2>/dev/null || true)
            msg="merge-seg running"
            [[ -n "$progress" ]] && msg+=" stage $progress"
            [[ -n "$val" ]] && msg+=" val_iu=$val"
            log "$msg"
        fi
    fi

    # ── r2-train ───────────────────────────────────────────────────────
    if [[ "$HTR_DONE" -eq 0 ]]; then
        htr_proc=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "pgrep -f 'keto[s].*gm-htr-r2' 2>/dev/null | head -1" 2>/dev/null || true)
        htr_model=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "ls ~/src/gm-htr-r2.mlmodel_best.mlmodel 2>/dev/null" 2>/dev/null || true)
        if [[ -z "$htr_proc" && -n "$htr_model" ]]; then
            log "r2-train DONE — best model: $htr_model"
            dest=$(fetch_model "$htr_model" "son-of-gm-r2.mlmodel")
            update_env "TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH" "$dest"
            commit_env "son-of-gm-r2"
            HTR_DONE=1
        else
            acc=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "grep -oP 'val_accuracy:\s*\K[0-9.]+' \$(ls -t ~/htr-r2-*.log ~/htr-r2-resume*.log 2>/dev/null | head -1) 2>/dev/null | tail -1" 2>/dev/null || true)
            msg="r2-train running"
            [[ -n "$acc" ]] && msg+=" val_accuracy=$acc"
            log "$msg"
        fi
    fi

    # ── r3-train ───────────────────────────────────────────────────────
    if [[ "$HTR_DONE" -eq 1 ]]; then
        r3_proc=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "pgrep -f 'keto[s].*gm-htr-r3' 2>/dev/null | head -1" 2>/dev/null || true)
        r3_model=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "ls ~/src/gm-htr-r3.mlmodel_best.mlmodel 2>/dev/null" 2>/dev/null || true)
        if [[ -n "$r3_proc" || -z "$r3_model" ]]; then
            acc=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "grep -oP 'val_accuracy:\s*\K[0-9.]+' \$(ls -t ~/htr-r3-*.log 2>/dev/null | head -1) 2>/dev/null | tail -1" 2>/dev/null || true)
            msg="r3-train running"
            [[ -n "$acc" ]] && msg+=" val_accuracy=$acc"
            [[ -n "$r3_proc" ]] && log "$msg"
        elif [[ -n "$r3_model" ]]; then
            log "r3-train DONE — best model: $r3_model"
            dest=$(fetch_model "$r3_model" "son-of-gm-r3.mlmodel")
            update_env "TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH" "$dest"
            commit_env "son-of-gm-r3"
            HTR_DONE=2
        fi
    fi

    # ── son-of-gm ─────────────────────────────────────────────────────
    if [[ "$HTR_DONE" -ge 2 && "$SOG_DONE" -eq 0 ]]; then
        sog_proc=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "pgrep -f 'keto[s].*son-of-gm' 2>/dev/null | head -1" 2>/dev/null || true)
        sog_model=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "ls ~/src/son-of-gm.mlmodel_best.mlmodel 2>/dev/null" 2>/dev/null || true)
        if [[ -z "$sog_proc" && -n "$sog_model" ]]; then
            log "son-of-gm DONE — best model: $sog_model"
            dest=$(fetch_model "$sog_model" "son-of-gm.mlmodel")
            update_env "TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH" "$dest"
            commit_env "son-of-gm"
            SOG_DONE=1
        elif [[ -n "$sog_proc" ]]; then
            acc=$(ssh -o ConnectTimeout=30 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 "$SERVER" "grep -oP 'val_accuracy:\s*\K[0-9.]+' \$(ls -t ~/son-of-gm.log 2>/dev/null | head -1) 2>/dev/null | tail -1" 2>/dev/null || true)
            msg="son-of-gm running"
            [[ -n "$acc" ]] && msg+=" val_accuracy=$acc"
            log "$msg"
        else
            log "son-of-gm queued (waiting for r3 to finish)"
        fi
    fi

    # ── all done ──────────────────────────────────────────────────────
    if [[ "$SEG_DONE" -eq 1 && "$HTR_DONE" -ge 2 && "$SOG_DONE" -eq 1 ]]; then
        log "All jobs complete. Exiting."
        exit 0
    fi

    sleep 300  # poll every 5 minutes
done
