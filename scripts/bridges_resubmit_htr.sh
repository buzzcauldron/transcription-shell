#!/usr/bin/env bash
# Smart HTR resubmit on Bridges login (idempotent).
#
#   bash scripts/bridges_resubmit_htr.sh            # submit missing jobs
#   bash scripts/bridges_resubmit_htr.sh --dry-run
#
# Prefers: keep running jobs → resume timed-out r6 → downstream only when r6 done
# → full bridges_start chain when nothing exists yet.
set -euo pipefail

SRC="${SRC:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
SCRIPTS="$SRC/scripts"
GT="$SRC/latin-corpus-gt"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

log() { echo "[htr-resubmit] $(date '+%H:%M:%S') $*"; }
run() {
  if [[ "$DRY" -eq 1 ]]; then
    log "[dry-run] $*"
  else
    log "$*"
    "$@"
  fi
}

running_job() {
  local name="$1"
  squeue -u "$USER" -h -o "%j %T" 2>/dev/null \
    | awk -v n="$name" '$1 == n && ($2 == "RUNNING" || $2 == "PENDING") { found = 1 } END { exit !found }'
}

last_job_state() {
  local name="$1"
  sacct -u "$USER" --name="$name" \
    --starttime="$(date -d '7 days ago' +%Y-%m-%d 2>/dev/null || date -v-7d +%Y-%m-%d)" \
    --format=JobName,State -P -n 2>/dev/null \
    | awk -F'|' -v n="$name" '$1 == n { state = $2 } END { print state }'
}

# Cancel orphaned dependency jobs (blocks new submissions).
while IFS= read -r jid; do
  [[ -z "$jid" ]] && continue
  run scancel "$jid" || true
done < <(squeue -u "$USER" -h -o "%i %r" 2>/dev/null | awk '$2 == "(DependencyNeverSatisfied)" { print $1 }')

if running_job "htr-r6-core"; then
  log "htr-r6-core active — nothing to submit"
  exit 0
fi

R6_MODEL="$SRC/gm-htr-r6-core_best.mlmodel"
R6_CKPT="$(ls -t "$SRC/gm-htr-r6-core"/checkpoint_*.ckpt 2>/dev/null | head -1 || true)"

if [[ -s "$R6_MODEL" ]]; then
  log "r6-core model present — checking downstream jobs"
  submitted=0

  if ! running_job "htr-r7-full"; then
    if [[ ! -s "$SRC/gm-htr-r7-full_best.mlmodel" ]] || [[ "$(last_job_state htr-r7-full)" == "FAILED" || "$(last_job_state htr-r7-full)" == "TIMEOUT" ]]; then
      run bash -lc "cd '$SRC' && sbatch --parsable -A hum260002p '$SCRIPTS/r7_full_retrain.sbatch'"
      submitted=1
    fi
  fi

  if ! running_job "htr-anglicana"; then
    if [[ -s "$GT/metadata.jsonl" ]] && { [[ ! -s "$SRC/gm-htr-anglicana_best.mlmodel" ]] || [[ "$(last_job_state htr-anglicana)" == "FAILED" || "$(last_job_state htr-anglicana)" == "TIMEOUT" ]]; }; then
      run bash -lc "cd '$SRC' && sbatch --parsable -A hum260002p '$SCRIPTS/r_anglicana_legal.sbatch'"
      submitted=1
    fi
  fi

  [[ "$submitted" -eq 1 ]] && exit 0
  log "downstream jobs running or complete"
  exit 0
fi

if [[ -n "$R6_CKPT" ]]; then
  state="$(last_job_state htr-r6-core)"
  if [[ "$state" == "TIMEOUT" || "$state" == "FAILED" ]]; then
    log "resuming r6-core from checkpoint ($R6_CKPT)"
    run bash -lc "cd '$SRC' && sbatch --parsable -A hum260002p '$SCRIPTS/r6_core_resume.sbatch'"
    exit 0
  fi
fi

log "no r6 model/checkpoint — submitting full chain via bridges_start.sh"
run bash "$SCRIPTS/bridges_start.sh"
