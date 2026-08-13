#!/usr/bin/env bash
# Watch running acquire processes, publish interim coverage, finalize harvest.
#
# Does not kill active acquire workers. When acquire_queue is fully processed
# (runner exited) and optionally needs_review runner has exited, runs download
# status sync + full audit + repository samples and writes logs/DONE.
#
# Usage on Akdeniz:
#   nohup bash scripts/computus/harvest_supervisor.sh \
#     --harvest-root /mnt/constantinople/seth/latin-ms-workspace/computus_web_harvest \
#     >>HARVEST/logs/supervisor.log 2>&1 &
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PY="${PYTHON:-python3}"
HARVEST_ROOT="${HARVEST_ROOT:-}"
POLL=120
REQUIRE_NEEDS_REVIEW=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --harvest-root) HARVEST_ROOT="$2"; shift 2 ;;
    --poll) POLL="$2"; shift 2 ;;
    --wait-needs-review) REQUIRE_NEEDS_REVIEW=true; shift ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$HARVEST_ROOT" ]]; then
  if [[ -d /mnt/constantinople/seth/latin-ms-workspace/computus_web_harvest ]]; then
    HARVEST_ROOT=/mnt/constantinople/seth/latin-ms-workspace/computus_web_harvest
  else
    HARVEST_ROOT="$ROOT/references/computus-library/web_harvest"
  fi
fi
if [[ -d /mnt/constantinople/seth/latin-ms-workspace/jobs ]]; then
  JOBS_ROOT=/mnt/constantinople/seth/latin-ms-workspace/jobs
else
  JOBS_ROOT="${JOBS_ROOT:-$HOME/latin-ms-workspace/jobs}"
fi

REG_DIR="$HARVEST_ROOT/registry"
OUT_BASE="$ROOT/references/computus-library/web_harvest"
mkdir -p "$HARVEST_ROOT/logs" "$HARVEST_ROOT/reports" "$OUT_BASE/reports"

log() { echo "[supervisor $(date -Iseconds)] $*"; }

acquire_running() {
  # true if confirmed acquire runner still alive
  pgrep -f "run_acquire_queue.py --queue .*/acquire_queue.jsonl" >/dev/null 2>&1
}

needs_review_running() {
  pgrep -f "run_acquire_queue.py --queue .*/needs_review_acquire_queue.jsonl" >/dev/null 2>&1
}

run_audit() {
  local tag="$1"
  local reg="$REG_DIR/union_registry_discovered.jsonl"
  [[ -f "$reg" ]] || reg="$OUT_BASE/union_registry.jsonl"
  log "audit ($tag)"
  "$PY" "$ROOT/scripts/computus/update_download_status.py" \
    --registry "$reg" \
    --jobs-root "$JOBS_ROOT" \
    --out "$REG_DIR/union_registry_with_downloads.jsonl" || true
  local q_args=()
  for q in "$HARVEST_ROOT/queues/acquire_queue.jsonl" \
           "$HARVEST_ROOT/queues/needs_review_acquire_queue.jsonl"; do
    [[ -f "$q" ]] && q_args+=(--queue "$q")
  done
  "$PY" "$ROOT/scripts/computus/audit_coverage.py" \
    --registry "$REG_DIR/union_registry_with_downloads.jsonl" \
    --jobs-root "$JOBS_ROOT" \
    --out-dir "$HARVEST_ROOT/reports" \
    "${q_args[@]}" || true
  "$PY" "$ROOT/scripts/computus/validate_repository_samples.py" \
    --jobs-root "$JOBS_ROOT" \
    --out-dir "$HARVEST_ROOT/reports" \
    "${q_args[@]}" || true
  mkdir -p "$OUT_BASE/reports"
  cp -a "$HARVEST_ROOT/reports/." "$OUT_BASE/reports/" 2>/dev/null || true
  log "audit ($tag) published → $HARVEST_ROOT/reports"
}

# Immediate interim report
run_audit interim
last_audit=$(date +%s)

log "watching acquire workers poll=${POLL}s wait_needs_review=$REQUIRE_NEEDS_REVIEW"
while true; do
  conf_run=false
  nr_run=false
  acquire_running && conf_run=true
  needs_review_running && nr_run=true

  if [[ "$conf_run" == false ]]; then
    if [[ "$REQUIRE_NEEDS_REVIEW" == true && "$nr_run" == true ]]; then
      log "confirmed acquire finished; still waiting on needs_review runner"
      run_audit mid
      last_audit=$(date +%s)
      sleep "$POLL"
      continue
    fi
    run_audit final
    {
      echo "DONE $(date -Iseconds)"
      echo "confirmed_acquire_running=false"
      echo "needs_review_acquire_running=$nr_run"
      echo "harvest_root=$HARVEST_ROOT"
    } | tee "$HARVEST_ROOT/logs/DONE"
    log "wrote $HARVEST_ROOT/logs/DONE"
    exit 0
  fi

  now=$(date +%s)
  if (( now - last_audit >= 1800 )); then
    run_audit interim
    last_audit=$now
  fi
  sleep "$POLL"
done
