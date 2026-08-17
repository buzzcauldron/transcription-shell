#!/usr/bin/env bash
# HTR control non-computus jobs with gm-htr-r5-best (LLM off). Does not touch
# the computus jobs/ tree or HIST_SLUGS.
#
# Akdeniz 4090 is often already on computus harvest — prefer Bridges then:
#   bash scripts/control_miscellany/sync_control_jobs_to_bridges.sh --all
#   ssh bridges2 'bash ~/…/submit_bridges_control_htr.sh --all'
#
# On Akdeniz (only when the 4090 is free):
#   bash scripts/control_miscellany/run_control_htr.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PY="${PYTHON:-python3}"

export STREAM_DOC_TYPE="${STREAM_DOC_TYPE:-medieval_latin_miscellany}"
export STREAM_LLM_MODE="${STREAM_LLM_MODE:-off}"
case "$STREAM_LLM_MODE" in
  off|correct) ;;
  *) echo "coerce STREAM_LLM_MODE=$STREAM_LLM_MODE → correct (autocorrect only)" >&2; export STREAM_LLM_MODE=correct ;;
esac
export STREAM_HTR_COMBINATION="${STREAM_HTR_COMBINATION:-kraken_htr}"
export STREAM_PROVIDER="${STREAM_PROVIDER:-gemini}"
MAX_CONCURRENT="${PIPELINE_MAX_CONCURRENT:-1}"
MIN_IMAGES="${PIPELINE_MIN_IMAGES:-10}"
POLL_SEC="${PIPELINE_POLL_SEC:-120}"

if [[ -d /mnt/constantinople/seth/latin-ms-workspace ]]; then
  JOBS_ROOT="${JOBS_ROOT:-/mnt/constantinople/seth/latin-ms-workspace/jobs_control_noncomputus}"
  HARVEST_ROOT="${HARVEST_ROOT:-/mnt/constantinople/seth/latin-ms-workspace/control_miscellany_harvest}"
else
  JOBS_ROOT="${JOBS_ROOT:-$HOME/latin-ms-workspace/jobs_control_noncomputus}"
  HARVEST_ROOT="${HARVEST_ROOT:-$ROOT/references/control-miscellany/web_harvest}"
fi

R5=""
for cand in \
  "${TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH:-}" \
  "$HOME/src/gm-htr-r5-best.mlmodel" \
  "$HOME/src/latin_documents/gm-htr-r5-best.mlmodel"; do
  [[ -n "$cand" && -f "$cand" ]] && R5="$cand" && break
done
if [[ -z "$R5" ]]; then
  echo "missing gm-htr-r5-best.mlmodel (looked in ~/src and ~/src/latin_documents)" >&2
  exit 1
fi
export TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH="$R5"
export TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH="${TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH:-$HOME/src/gm-seg.mlmodel}"

VENV=""
for cand in "$ROOT/.venv-lineation" "$HOME/.venv-lineation" "$HOME/.venv-kraken"; do
  if [[ -x "$cand/bin/python" ]]; then VENV="$cand"; break; fi
done
[[ -n "$VENV" ]] || VENV="$HOME/.venv-kraken"
PY_HTR="$VENV/bin/python"
[[ -x "$PY_HTR" ]] || PY_HTR="$(command -v python3)"

mkdir -p "$HARVEST_ROOT/logs" "$JOBS_ROOT"
LOG="$HARVEST_ROOT/logs/control_htr_supervisor.log"
log() { echo "[control-htr $(date -Iseconds)] $*" | tee -a "$LOG"; }

alive_pid() {
  local f="$1" p
  [[ -f "$f" ]] || return 1
  p=$(tr -d '[:space:]' < "$f" 2>/dev/null || true)
  [[ -n "$p" ]] || return 1
  kill -0 "$p" 2>/dev/null
}
watcher_running() { alive_pid "$1/status/watch_transcribe.pid"; }

count_images() {
  local d="$1/00_sources_chunks"
  [[ -d "$d" ]] || { echo 0; return; }
  find "$d" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.tif' \) 2>/dev/null | wc -l | tr -d ' '
}

start_watcher() {
  local job="$1" id pid
  id=$(basename "$job")
  mkdir -p "$job"/{logs,status,scripts,01_pages_2500,03_artifacts_2500,transcription_batches}
  cp -f "$ROOT/scripts/remote_stream_watch_transcribe.py" "$job/scripts/"
  nohup env \
    STREAM_JOB_DIR="$job" \
    STREAM_DOC_TYPE="$STREAM_DOC_TYPE" \
    STREAM_PROVIDER="$STREAM_PROVIDER" \
    STREAM_LLM_MODE="$STREAM_LLM_MODE" \
    STREAM_HTR_COMBINATION="$STREAM_HTR_COMBINATION" \
    STREAM_BATCH_SIZE="${STREAM_BATCH_SIZE:-4}" \
    STREAM_IDLE_LIMIT="${STREAM_IDLE_LIMIT:-30}" \
    STREAM_CONTINUE_ON_LINEATION_FAILURE=0 \
    STREAM_EXPAND=0 \
    STREAM_TRANSCRIPTION_SHELL_ROOT="$ROOT" \
    STREAM_TRANSCRIPTION_SHELL_VENV="$VENV" \
    EXPAND_DIPLOMATIC_ENABLED=0 \
    TRANSCRIBER_SHELL_EXPAND_DIPLOMATIC=0 \
    TRANSCRIBER_SHELL_AUTO_EFFICIENCY=1 \
    TRANSCRIBER_SHELL_REQUIRE_HTR_BEFORE_LLM=1 \
    TRANSCRIBER_SHELL_HTR_PARALLEL=0 \
    TRANSCRIBER_SHELL_HTR_COMBINATION="$STREAM_HTR_COMBINATION" \
    TRANSCRIBER_SHELL_LLM_MODE="$STREAM_LLM_MODE" \
    TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH="$R5" \
    TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH="${TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH}" \
    "$PY_HTR" "$job/scripts/remote_stream_watch_transcribe.py" \
    >> "$job/logs/watch_transcribe.nohup.log" 2>&1 &
  pid=$!
  echo $pid > "$job/status/watch_transcribe.pid"
  log "STARTED_HTR id=$id pid=$pid model=$R5 doc_type=$STREAM_DOC_TYPE llm=$STREAM_LLM_MODE"
}

log "jobs=$JOBS_ROOT model=$R5 doc_type=$STREAM_DOC_TYPE llm=$STREAM_LLM_MODE max=$MAX_CONCURRENT"
echo $$ > "$HARVEST_ROOT/control_htr_supervisor.pid"

while true; do
  active=0
  started=0
  pending=0
  for job in "$JOBS_ROOT"/ctrl_*; do
    [[ -d "$job" ]] || continue
    [[ -f "$job/status/acquire.DONE" ]] || continue
    [[ -f "$job/status/htr_bridges.DONE" || -f "$job/status/pipeline.DONE" ]] && continue
    n=$(count_images "$job")
    [[ "$n" -ge "$MIN_IMAGES" ]] || continue
    pending=$((pending+1))
    if watcher_running "$job"; then
      active=$((active+1))
      continue
    fi
    if [[ "$active" -ge "$MAX_CONCURRENT" ]]; then
      continue
    fi
    start_watcher "$job"
    active=$((active+1))
    started=$((started+1))
  done
  acq_busy=false
  pgrep -f "run_acquire_queue.py" >/dev/null 2>&1 && acq_busy=true
  log "tick pending=$pending active=$active started_now=$started acquire_busy=$acq_busy"
  if [[ "$pending" -eq 0 && "$active" -eq 0 && "$acq_busy" == false ]]; then
    log "DONE no ready control jobs"
    exit 0
  fi
  sleep "$POLL_SEC"
done
