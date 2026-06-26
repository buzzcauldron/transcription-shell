#!/usr/bin/env bash
# Canonical Bridges training entry point.
#
# All prep + training runs on GPU-shared compute nodes.
# No RM partition (wrong QoS for this allocation). No login-node work.
#
# Job chain:
#   r6-core  -- inline corpus prep (no Bullinger) + fine-tune from r2
#   r7-full  -- afterok:r6-core -- full prep (with Bullinger) + fine-tune from r6-core
#   anglicana -- afterok:r6-core -- KB27/CP40/JUST1 Anglicana filter + fine-tune from r2
#
# Usage (run on a Bridges login node):
#   bash bridges_start.sh            # submit full chain (idempotent)
#   bash bridges_start.sh --status   # show queue + key file status
#   bash bridges_start.sh --cancel   # cancel all htr-* training jobs
#   bash bridges_start.sh --logs     # tail latest output from each running job

set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
SCRIPTS="$SRC/scripts"

log() { echo "[bridges] $(date '+%H:%M:%S') $*"; }

show_status() {
  echo "=== Queue ==="
  squeue -u "$USER" --format="%.10i %.12P %.22j %.8T %.10M %r" 2>/dev/null || true
  echo ""
  echo "=== Key files ==="
  for f in \
    "$GT/metadata.jsonl" \
    "$GT/core_train_manifest.txt" \
    "$GT/full_train_manifest.txt" \
    "$GT/anglicana_train_manifest.txt" \
    "$SRC/gm-htr-r6-core_best.mlmodel" \
    "$SRC/gm-htr-r7-full_best.mlmodel" \
    "$SRC/gm-htr-anglicana_best.mlmodel"; do
    if [[ -s "$f" ]]; then
      sz=$(wc -l < "$f" 2>/dev/null || wc -c < "$f")
      printf "  OK  %-40s (%s lines)\n" "$(basename "$f")" "$sz"
    else
      printf "  --  %s\n" "$(basename "$f")"
    fi
  done
}

show_logs() {
  for log_file in $(ls -t "$SRC"/htr-r6-core-*.out "$SRC"/htr-anglicana-*.out "$SRC"/htr-r7-full-*.out 2>/dev/null | head -6); do
    echo ""
    echo "--- $(basename "$log_file") ---"
    tail -10 "$log_file"
  done
}

cancel_all() {
  local cancelled=0
  while IFS= read -r line; do
    jid=$(echo "$line" | awk '{print $1}')
    jname=$(echo "$line" | awk '{print $2}')
    log "cancelling $jname (job $jid)"
    scancel "$jid" || true
    ((cancelled++)) || true
  done < <(squeue -u "$USER" -h -o "%i %j" 2>/dev/null | awk '$2 ~ /^htr-/')
  [[ "$cancelled" -eq 0 ]] && log "no htr-* jobs to cancel"
}

running_job() {
  local name="$1"
  squeue -u "$USER" -h -o "%i %j %T" 2>/dev/null \
    | awk -v n="$name" '$2 == n && ($3 == "RUNNING" || $3 == "PENDING") {print $1}' \
    | head -1
}

case "${1:-}" in
  --status)   show_status; exit 0 ;;
  --logs)     show_logs; exit 0 ;;
  --cancel|--cancel-all) cancel_all; exit 0 ;;
  "")         ;;
  *) echo "Usage: $0 [--status|--logs|--cancel]"; exit 1 ;;
esac

# Abort if r6-core is already queued/running (most likely a restart attempt).
  if existing=$(running_job "htr-r6-core"); [[ -n "$existing" ]]; then
  log "r6-core already active (job $existing) — nothing to submit"
elif existing=$(running_job "htr-r6-core-r"); [[ -n "$existing" ]]; then
  log "r6-core-r resume already active (job $existing) — nothing to submit"
  log "Use --status to check progress or --cancel to restart from scratch"
  show_status
  exit 0
fi

# Clean up any jobs stuck in DependencyNeverSatisfied.
while IFS= read -r line; do
  jid=$(echo "$line" | awk '{print $1}')
  log "cancelling orphaned job $jid (DependencyNeverSatisfied)"
  scancel "$jid" || true
done < <(squeue -u "$USER" -h -o "%i %j %r" 2>/dev/null | awk '$3 == "DependencyNeverSatisfied" {print $1, $2, $3}')

for f in r6_core_retrain.sbatch r7_full_retrain.sbatch r_anglicana_legal.sbatch bridges_prep_env.sh; do
  [[ -f "$SCRIPTS/$f" ]] || { echo "ERROR: missing $SCRIPTS/$f" >&2; exit 1; }
done

[[ -d "$SRC/htr-corpora" ]] || { echo "ERROR: htr-corpora missing on Ocean" >&2; exit 1; }
[[ -f "$SRC/gm-htr-r2.mlmodel_best.mlmodel" ]] || { echo "ERROR: base model r2 missing" >&2; exit 1; }
[[ -x "$SRC/../kraken-venv/bin/ketos" ]] || [[ -f "$SCRIPTS/bridges_kraken_activate.sh" ]] \
  || { echo "ERROR: kraken venv / activate missing" >&2; exit 1; }

log "preflight: clean python for corpus prep (login node; non-fatal)..."
# shellcheck disable=SC1091
if source "$SCRIPTS/bridges_prep_env.sh" 2>/dev/null; then
  log "preflight OK ($PY_RUN)"
else
  log "preflight skipped on login — corpus prep runs on GPU compute node"
fi

cd "$SRC"
log "submitting r6-core (inline corpus prep + training from r2)..."
R6=$(sbatch --parsable -A hum260002p "$SCRIPTS/r6_core_retrain.sbatch")
log "  r6-core   job $R6"

log "submitting r7-full (afterok:$R6)..."
R7=$(sbatch --parsable --dependency=afterok:"$R6" "$SCRIPTS/r7_full_retrain.sbatch")
log "  r7-full   job $R7"

log "submitting anglicana (afterok:$R7, KB27/CP40/JUST1)..."
ANG=$(sbatch --parsable --dependency=afterok:"$R7" "$SCRIPTS/r_anglicana_legal.sbatch")
log "  anglicana job $ANG"

echo ""
log "Chain live. Monitor:"
log "  bash $SCRIPTS/bridges_start.sh --status"
log "  bash $SCRIPTS/bridges_start.sh --logs"
log "  tail -f $SRC/htr-r6-core-${R6}.out"
echo ""
log "Auto-pull on Mac (run locally once chain finishes):"
log "  bash scripts/bridges_watch_pull.sh --job $ANG --rescore"
log "  bash scripts/bridges_watch_pull.sh --job $R7 --rescore"
