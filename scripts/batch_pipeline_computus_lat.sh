#!/usr/bin/env bash
# Deploy + start HTR supervisor for finished computus.lat acquires (clat_*).
#
# Default: late-night akdeniz only (quiet hours, server local), 1 concurrent watcher.
# Per-MS: starts as each acquire finishes (does not wait for whole queue).
#
# Usage:
#   bash scripts/batch_pipeline_computus_lat.sh
#   PIPELINE_BACKEND=force_akdeniz bash scripts/batch_pipeline_computus_lat.sh
#   PIPELINE_BACKEND=bridges bash scripts/batch_pipeline_computus_lat.sh
#
# Overrides: LATE_NIGHT_START/END, PIPELINE_MAX_CONCURRENT, PIPELINE_MIN_IMAGES, PIPELINE_POLL_SEC

set -euo pipefail

REMOTE="${STREAM_REMOTE:-akdeniz}"
WS_REMOTE="${LATIN_MS_WORKSPACE_REMOTE:-/mnt/constantinople/seth/latin-ms-workspace}"
QUEUE_DIR="$WS_REMOTE/computus_lat_queue"
TSHELL_REMOTE="${TSHELL_REMOTE:-/mnt/constantinople/seth/Projects/transcription-shell}"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export LATIN_MS_WORKSPACE_REMOTE="$WS_REMOTE"
export TSHELL_REMOTE
export LATE_NIGHT_START="${LATE_NIGHT_START:-23}"
export LATE_NIGHT_END="${LATE_NIGHT_END:-8}"
export PIPELINE_MAX_CONCURRENT="${PIPELINE_MAX_CONCURRENT:-1}"
export PIPELINE_MIN_IMAGES="${PIPELINE_MIN_IMAGES:-10}"
export PIPELINE_BACKEND="${PIPELINE_BACKEND:-akdeniz_latenight}"
export STREAM_DOC_TYPE="${STREAM_DOC_TYPE:-computus_medieval_latin}"
export STREAM_PROVIDER="${STREAM_PROVIDER:-gemini}"
export STREAM_BATCH_SIZE="${STREAM_BATCH_SIZE:-4}"
export STREAM_IDLE_LIMIT="${STREAM_IDLE_LIMIT:-30}"
export PIPELINE_POLL_SEC="${PIPELINE_POLL_SEC:-300}"

mkdir -p /tmp/computus_lat_pipeline_deploy
cp -f \
  "$LOCAL_DIR/remote_stream_watch_transcribe.py" \
  "$LOCAL_DIR/remote_stream_watch_partial_stylo.py" \
  "$LOCAL_DIR/remote_stream_start_watchers.sh" \
  /tmp/computus_lat_pipeline_deploy/

python3 - <<'PY' > /tmp/computus_lat_pipeline_deploy/run_pipeline_supervisor.sh
import os

ws = os.environ["LATIN_MS_WORKSPACE_REMOTE"]
tshell = os.environ["TSHELL_REMOTE"]
cfg = {k: os.environ[k] for k in [
    "LATE_NIGHT_START", "LATE_NIGHT_END", "PIPELINE_MAX_CONCURRENT", "PIPELINE_MIN_IMAGES",
    "PIPELINE_BACKEND", "STREAM_DOC_TYPE", "STREAM_PROVIDER", "STREAM_BATCH_SIZE",
    "STREAM_IDLE_LIMIT", "PIPELINE_POLL_SEC",
]}

script = r'''#!/usr/bin/env bash
# HTR for finished clat_* acquires (computus.lat).
# Note: avoid set -e so false (( arithmetic )) quiet-hour checks never kill the loop.
set -uo pipefail

WS="__WS__"
JOBS="$WS/jobs"
QDIR="$WS/computus_lat_queue"
LOG="$QDIR/logs/pipeline_supervisor.log"
STATE="$QDIR/pipeline_state"
SCRIPTS="$QDIR/scripts"
TSHELL="__TSHELL__"
VENV=""
for cand in "$TSHELL/.venv-lineation" "$HOME/.venv-lineation" "$HOME/.venv-kraken"; do
  if [[ -x "$cand/bin/python" ]]; then VENV="$cand"; break; fi
done
[[ -n "$VENV" ]] || VENV="$HOME/.venv-kraken"

LATE_NIGHT_START=__LATE_NIGHT_START__
LATE_NIGHT_END=__LATE_NIGHT_END__
MAX_CONCURRENT=__PIPELINE_MAX_CONCURRENT__
MIN_IMAGES=__PIPELINE_MIN_IMAGES__
PIPELINE_BACKEND="__PIPELINE_BACKEND__"
DOC_TYPE="__STREAM_DOC_TYPE__"
PROVIDER="__STREAM_PROVIDER__"
BATCH_SIZE=__STREAM_BATCH_SIZE__
IDLE_LIMIT=__STREAM_IDLE_LIMIT__
POLL_SEC=__PIPELINE_POLL_SEC__

mkdir -p "$STATE" "$QDIR/logs"
echo $$ > "$QDIR/pipeline_supervisor.pid"

log() { echo "$(date -Iseconds) $*" | tee -a "$LOG"; }

alive_pid() {
  local f="$1" p
  [[ -f "$f" ]] || return 1
  p=$(tr -d '[:space:]' < "$f" 2>/dev/null || true)
  [[ -n "$p" ]] || return 1
  kill -0 "$p" 2>/dev/null
}

acquire_running() {
  local job="$1" f
  for f in "$job"/status/acquire_*.pid; do
    [[ -f "$f" ]] || continue
    alive_pid "$f" && return 0
  done
  return 1
}

watcher_running() { alive_pid "$1/status/watch_transcribe.pid"; }

image_count() {
  find "$1/00_sources_chunks" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) 2>/dev/null | wc -l | tr -d ' '
}

yaml_count() {
  find "$1/03_artifacts_2500" -name '*_transcription.yaml' 2>/dev/null | wc -l | tr -d ' '
}

is_quiet_hours() {
  local h s e
  h=$((10#$(date +%H)))
  s=$LATE_NIGHT_START
  e=$LATE_NIGHT_END
  if (( s < e )); then
    if (( h >= s && h < e )); then return 0; fi
    return 1
  else
    if (( h >= s || h < e )); then return 0; fi
    return 1
  fi
}

backend_allows_start() {
  case "$PIPELINE_BACKEND" in
    force_akdeniz|bridges) return 0 ;;
    *) is_quiet_hours; return $? ;;
  esac
}

count_active_watchers() {
  local n=0 j
  for j in "$JOBS"/clat_*; do
    [[ -d "$j" ]] || continue
    watcher_running "$j" && n=$((n+1))
  done
  echo "$n"
}

start_watcher_akdeniz() {
  local job="$1" id pid
  id=$(basename "$job")
  mkdir -p "$job"/{logs,status,scripts,01_pages_2500,03_artifacts_2500,transcription_batches}
  cp -f "$SCRIPTS/remote_stream_watch_transcribe.py" "$job/scripts/" 2>/dev/null || true
  local py="$VENV/bin/python"
  [[ -x "$py" ]] || py=$(command -v python3)
  nohup env \
    STREAM_JOB_DIR="$job" \
    STREAM_DOC_TYPE="$DOC_TYPE" \
    STREAM_PROVIDER="$PROVIDER" \
    STREAM_BATCH_SIZE="$BATCH_SIZE" \
    STREAM_IDLE_LIMIT="$IDLE_LIMIT" \
    STREAM_TRANSCRIPTION_SHELL_ROOT="$TSHELL" \
    STREAM_TRANSCRIPTION_SHELL_VENV="$VENV" \
    TRANSCRIBER_SHELL_AUTO_EFFICIENCY=1 \
    "$py" "$job/scripts/remote_stream_watch_transcribe.py" \
    >> "$job/logs/watch_transcribe.nohup.log" 2>&1 &
  pid=$!
  echo $pid > "$job/status/watch_transcribe.pid"
  date -Iseconds > "$STATE/${id}.started"
  log "STARTED_WATCHER id=$id pid=$pid backend=akdeniz images=$(image_count "$job") yaml=$(yaml_count "$job")"
}

mark_bridges_ready() {
  local job="$1" id
  id=$(basename "$job")
  echo "$job" >> "$QDIR/bridges_ready.list"
  date -Iseconds > "$STATE/${id}.bridges_queued"
  log "QUEUED_BRIDGES id=$id images=$(image_count "$job")"
}

log "pipeline supervisor start backend=$PIPELINE_BACKEND quiet=${LATE_NIGHT_START}-${LATE_NIGHT_END} max=$MAX_CONCURRENT min_img=$MIN_IMAGES venv=$VENV"

while true; do
  ready=0 started=0 waiting_hours=0
  for job in "$JOBS"/clat_*; do
    [[ -d "$job" ]] || continue
    id=$(basename "$job")
    n=$(image_count "$job")
    [[ "$n" -ge "$MIN_IMAGES" ]] || continue
    acquire_running "$job" && continue
    if watcher_running "$job"; then continue; fi
    y=$(yaml_count "$job")
    if [[ "$y" -gt 0 && "$n" -gt 0 ]] && (( y * 10 >= n * 9 )); then
      touch "$STATE/${id}.done" 2>/dev/null || true
      continue
    fi
    if [[ -f "$STATE/${id}.started" ]] && ! watcher_running "$job"; then
      [[ -f "$STATE/${id}.done" ]] && continue
      rm -f "$STATE/${id}.started"
    fi
    ready=$((ready+1))
    if ! backend_allows_start; then
      waiting_hours=$((waiting_hours+1))
      continue
    fi
    active=$(count_active_watchers)
    if [[ "$active" -ge "$MAX_CONCURRENT" ]]; then
      log "THROTTLE active=$active max=$MAX_CONCURRENT ($id waiting)"
      break
    fi
    if [[ "$PIPELINE_BACKEND" == "bridges" ]]; then
      [[ -f "$STATE/${id}.bridges_queued" ]] || { mark_bridges_ready "$job"; started=$((started+1)); }
    else
      start_watcher_akdeniz "$job"
      started=$((started+1))
    fi
  done
  active=$(count_active_watchers)
  done_n=$(ls "$STATE"/*.done 2>/dev/null | wc -l | tr -d ' ')
  log "tick ready_unstarted=$ready active_watchers=$active started_now=$started waiting_quiet_hours=$waiting_hours done_markers=$done_n backend=$PIPELINE_BACKEND hour=$(date +%H)"
  sleep "$POLL_SEC"
done
'''

repl = {
    "__WS__": ws,
    "__TSHELL__": tshell,
    "__LATE_NIGHT_START__": cfg["LATE_NIGHT_START"],
    "__LATE_NIGHT_END__": cfg["LATE_NIGHT_END"],
    "__PIPELINE_MAX_CONCURRENT__": cfg["PIPELINE_MAX_CONCURRENT"],
    "__PIPELINE_MIN_IMAGES__": cfg["PIPELINE_MIN_IMAGES"],
    "__PIPELINE_BACKEND__": cfg["PIPELINE_BACKEND"],
    "__STREAM_DOC_TYPE__": cfg["STREAM_DOC_TYPE"],
    "__STREAM_PROVIDER__": cfg["STREAM_PROVIDER"],
    "__STREAM_BATCH_SIZE__": cfg["STREAM_BATCH_SIZE"],
    "__STREAM_IDLE_LIMIT__": cfg["STREAM_IDLE_LIMIT"],
    "__PIPELINE_POLL_SEC__": cfg["PIPELINE_POLL_SEC"],
}
for k, v in repl.items():
    script = script.replace(k, v)
print(script, end="")
PY

rsync -az /tmp/computus_lat_pipeline_deploy/ "$REMOTE:$QUEUE_DIR/deploy_tmp/"
ssh -n "$REMOTE" "
  set -e
  mkdir -p '$QUEUE_DIR/scripts' '$QUEUE_DIR/logs' '$QUEUE_DIR/pipeline_state'
  cp -f '$QUEUE_DIR/deploy_tmp/remote_stream_watch_transcribe.py' \
        '$QUEUE_DIR/deploy_tmp/remote_stream_watch_partial_stylo.py' \
        '$QUEUE_DIR/deploy_tmp/remote_stream_start_watchers.sh' \
        '$QUEUE_DIR/scripts/' 2>/dev/null || true
  cp -f '$QUEUE_DIR/deploy_tmp/run_pipeline_supervisor.sh' '$QUEUE_DIR/run_pipeline_supervisor.sh'
  chmod +x '$QUEUE_DIR/run_pipeline_supervisor.sh'
  chmod +x '$QUEUE_DIR/scripts'/remote_stream_* 2>/dev/null || true

  pkill -f 'run_pipeline_supervisor.sh' 2>/dev/null || true
  sleep 1
  setsid nohup bash '$QUEUE_DIR/run_pipeline_supervisor.sh' >> '$QUEUE_DIR/logs/pipeline_supervisor.nohup.log' 2>&1 < /dev/null &
  sleep 3
  echo SUPERVISOR_PID=\$(cat '$QUEUE_DIR/pipeline_supervisor.pid' 2>/dev/null || echo '?')
  tail -12 '$QUEUE_DIR/logs/pipeline_supervisor.log' 2>/dev/null || tail -12 '$QUEUE_DIR/logs/pipeline_supervisor.nohup.log'
"

echo ""
echo "Deployed pipeline supervisor on $REMOTE"
echo "  backend=$PIPELINE_BACKEND  quiet=${LATE_NIGHT_START}:00–${LATE_NIGHT_END}:00  max=$PIPELINE_MAX_CONCURRENT"
echo "  log: $QUEUE_DIR/logs/pipeline_supervisor.log"
echo "  force anytime: PIPELINE_BACKEND=force_akdeniz bash $0"
echo "  bridges list:  PIPELINE_BACKEND=bridges bash $0"
