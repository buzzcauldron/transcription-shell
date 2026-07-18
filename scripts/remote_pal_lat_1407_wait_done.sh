#!/usr/bin/env bash
# Run on akdeniz: wait for Pal. lat. 1407 transcription to finish, then mark complete.
set -euo pipefail

JOB="$HOME/latin-ms-workspace/jobs/pal_lat_1407"
POLL="${POLL:-300}"
LOG="$JOB/logs/watch_pipeline_complete.log"

log() { echo "[pal1407-done] $(date -Iseconds) $*" | tee -a "$LOG"; }

log "watching for pipeline completion"
while true; do
  pages=$(find "$JOB/01_pages_2500" -name '*.jpg' 2>/dev/null | wc -l | tr -d ' ')
  done=$(find "$JOB/03_artifacts_2500" -name '*_transcription.yaml' 2>/dev/null | wc -l | tr -d ' ')
  running=0
  for pidfile in "$JOB/status"/*.pid; do
    [[ -f "$pidfile" ]] || continue
    if kill -0 "$(cat "$pidfile")" 2>/dev/null; then running=1; break; fi
  done
  log "pages=$pages done=$done running=$running"
  if [[ "$pages" -gt 0 && "$done" -ge "$pages" && "$running" -eq 0 ]]; then
    date -Iseconds > "$JOB/status/pipeline_complete"
    log "pipeline complete"
    exit 0
  fi
  sleep "$POLL"
done
