#!/usr/bin/env bash
# Keep heavy akdeniz work inside OFF HOURS only.
#
# akdeniz is a shared lab machine, so the computus HTR run (6 workers, ~25 of 32
# cores) should not be competing with other people's daytime work. This guard
# starts the driver when the window opens and stops it when the window closes.
#
# Stopping mid-manuscript is safe and cheap: the batch runner passes
# --skip-successful and progress is per PAGE, so pages already recognized are
# kept and the next window resumes where this one stopped. Nothing is recomputed
# beyond the single page in flight.
#
# WINDOW (America/New_York, akdeniz's local time):
#   weeknights  19:00 -> 07:00
#   weekends    all day
# Override with OFFHOURS_START / OFFHOURS_END (hours, 0-23) and
# OFFHOURS_WEEKEND=0 to treat weekends as on-hours.
set -uo pipefail

START="${OFFHOURS_START:-19}"
END="${OFFHOURS_END:-7}"
WEEKEND_ALL="${OFFHOURS_WEEKEND:-1}"
RUNNER="${OFFHOURS_RUNNER:-$HOME/run_computus_raw.sh}"
SCREEN_NAME="${OFFHOURS_SCREEN:-computusraw}"
LOG="$HOME/offhours_guard.log"
POLL="${OFFHOURS_POLL:-300}"

log() { echo "[offhours $(date '+%F %H:%M:%S')] $*" | tee -a "$LOG"; }

in_window() {
  local h dow
  h=$(date +%-H)
  dow=$(date +%u)          # 1=Mon .. 7=Sun
  if [ "$WEEKEND_ALL" = 1 ] && [ "$dow" -ge 6 ]; then return 0; fi
  # Window wraps midnight when START > END.
  if [ "$START" -gt "$END" ]; then
    [ "$h" -ge "$START" ] || [ "$h" -lt "$END" ]
  else
    [ "$h" -ge "$START" ] && [ "$h" -lt "$END" ]
  fi
}

driver_running() { screen -ls 2>/dev/null | grep -q "[.]${SCREEN_NAME}"; }

stop_driver() {
  screen -S "$SCREEN_NAME" -X quit 2>/dev/null
  sleep 3
  # Stop the per-manuscript watchers too, or they keep the GPU busy after the
  # supervisor is gone. Kill by recorded PID, never by pattern -- a pattern
  # match on this project has killed the controlling ssh session before.
  local n=0 j pid
  for j in /mnt/constantinople/seth/latin-ms-workspace/jobs/*/status/watch_transcribe.pid; do
    [ -f "$j" ] || continue
    pid=$(tr -d '[:space:]' < "$j" 2>/dev/null)
    [ -n "$pid" ] || continue
    if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null && n=$((n+1)); fi
  done
  log "stopped driver and $n watcher(s)"
}

log "guard start: window ${START}:00-${END}:00 local, weekend_all=${WEEKEND_ALL}, runner=$RUNNER"
while true; do
  if in_window; then
    if ! driver_running; then
      log "OFF HOURS and driver down -> starting"
      screen -dmS "$SCREEN_NAME" bash -lc "$RUNNER > $HOME/computus_raw.log 2>&1"
    fi
  else
    if driver_running; then
      log "ON HOURS -> stopping (progress is per-page and resumes next window)"
      stop_driver
    fi
  fi
  sleep "$POLL"
done
