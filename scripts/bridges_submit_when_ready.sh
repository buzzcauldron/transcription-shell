#!/usr/bin/env bash
# Wait for kraken venv + corpus prep, then sbatch r6-core. Run on Bridges login:
#   nohup bash src/scripts/bridges_submit_when_ready.sh > ../submit-when-ready.log 2>&1 &
set -euo pipefail

PROJECT=/ocean/projects/hum260002p/sstrickland/transcriber-shell
SRC="$PROJECT/src"
LOG="$PROJECT/submit-when-ready.log"

log() { echo "[submit-ready] $(date -Iseconds) $*" | tee -a "$LOG"; }

log "waiting for ketos + core_train_manifest.txt"
for i in $(seq 1 120); do
  if [[ -x "$PROJECT/kraken-venv/bin/ketos" ]] \
     && [[ -s "$SRC/latin-corpus-gt/core_train_manifest.txt" ]]; then
    break
  fi
  sleep 60
  [[ "$i" -eq 120 ]] && { log "TIMEOUT — check kraken-venv-setup.log and corpus-prep.log"; exit 1; }
done

log "ready — submitting r6-core"
cd "$SRC"
JOB=$(sbatch scripts/r6_core_retrain.sbatch | awk '{print $4}')
log "submitted job $JOB"
log "monitor: tail -f $SRC/htr-r6-core-${JOB}.out"
