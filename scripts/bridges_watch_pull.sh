#!/usr/bin/env bash
# Watch Bridges SLURM jobs from the local Mac; pull best model weights when they complete.
#
# Usage:
#   bash scripts/bridges_watch_pull.sh                 # watch all hum260002p jobs
#   bash scripts/bridges_watch_pull.sh --job 41274868  # watch one specific job
#   bash scripts/bridges_watch_pull.sh --pull-only     # pull now, no waiting
#
# After pulling, optionally runs the GM stress matrix to rescore:
#   bash scripts/bridges_watch_pull.sh --rescore
set -euo pipefail

BRIDGES_LOGIN="${BRIDGES_LOGIN:-bridges2}"
BRIDGES_USER="${BRIDGES_USER:-sstrickland}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
POLL_INTERVAL=300  # 5 minutes

log() { echo "[bridges-watch] $(date -Iseconds) $*"; }

JOB_ID=""
PULL_ONLY=0
RESCORE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job)       JOB_ID="$2"; shift 2 ;;
    --pull-only) PULL_ONLY=1; shift ;;
    --rescore)   RESCORE=1;   shift ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

pull_models() {
  log "pulling best model weights from Bridges..."
  bash "$SRC/scripts/pull_bridges_htr_models.sh"
}

if [[ "$PULL_ONLY" -eq 1 ]]; then
  pull_models
  [[ "$RESCORE" -eq 1 ]] && bash "$SRC/scripts/bridges_rescore.sh"
  exit 0
fi

wait_for_job() {
  local jid="$1"
  log "watching job $jid (polling every ${POLL_INTERVAL}s)..."
  while true; do
    if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$BRIDGES_LOGIN" \
        "squeue -j $jid -h -o '%T'" 2>/dev/null | grep -q .; then
      log "job $jid no longer in queue — assuming complete"
      return 0
    fi
    local state
    state=$(ssh -o BatchMode=yes "$BRIDGES_LOGIN" "squeue -j $jid -h -o '%T'" 2>/dev/null || echo "")
    log "job $jid state: ${state:-UNKNOWN}"
    sleep "$POLL_INTERVAL"
  done
}

wait_for_any_job() {
  log "watching all $BRIDGES_USER jobs (polling every ${POLL_INTERVAL}s)..."
  while true; do
    local running
    running=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$BRIDGES_LOGIN" \
        "squeue -u $BRIDGES_USER -h -o '%i %T %j'" 2>/dev/null || echo "")
    if [[ -z "$running" ]]; then
      log "no running jobs for $BRIDGES_USER — training complete"
      return 0
    fi
    log "running jobs:"
    echo "$running" | while read -r line; do log "  $line"; done
    sleep "$POLL_INTERVAL"
  done
}

if [[ -n "$JOB_ID" ]]; then
  wait_for_job "$JOB_ID"
else
  wait_for_any_job
fi

pull_models

if [[ "$RESCORE" -eq 1 ]]; then
  log "rescoring stress matrix with new models..."
  python "$SRC/scripts/stress_shell_run.py" \
    --include-optional --all-htr \
    --cases BM-KB27 BM-MED-001 \
    2>&1 | tee "$SRC/artifacts/stress-shell/rescore-$(date +%Y%m%d-%H%M).log"
fi

log "done"
