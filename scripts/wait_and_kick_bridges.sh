#!/usr/bin/env bash
# Wait for akdeniz -> Bridges extras xfer, then run bridges_autostart.sh
set -euo pipefail

log() { echo "[wait-bridges] $(date -Iseconds) $*"; }

log "waiting for run_xfer_extras.sh to finish..."
while pgrep -f "bash.*run_xfer_extras.sh" >/dev/null 2>&1; do
  sleep 60
done
while pgrep -f "rsync.*data.bridges2.psc.edu" >/dev/null 2>&1; do
  sleep 30
done

log "extras complete — kicking Bridges autostart"
exec bash "${HOME}/src/scripts/bridges_autostart.sh" 2>&1 | tee -a "${HOME}/bridges-kick.log"
