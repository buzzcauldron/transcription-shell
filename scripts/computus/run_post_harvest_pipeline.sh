#!/usr/bin/env bash
# After web harvest: per manuscript, every time:
#   highest HTR → LLM autocorrect (skipped only on rate-limit caps) → expand-diplomatic rules → stylo
#
# Stages:
#   1. (optional) wait for first per-manuscript acquire.DONE (default)
#   2. build reviewed HTR queue from jobs with acquire.DONE + enough images
#   3. run HTR watchers on ready image trees as manuscripts complete
#   4. each watcher expands leftover pages and runs stylo before exiting
#
# Usage (on akdeniz):
#   bash scripts/computus/run_post_harvest_pipeline.sh --wait-manuscript
#   bash scripts/computus/run_post_harvest_pipeline.sh --wait-harvest   # full-queue only
#   bash scripts/computus/run_post_harvest_pipeline.sh --htr-only
#   bash scripts/computus/run_post_harvest_pipeline.sh --stylo-only
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PY="${PYTHON:-python3}"

HARVEST_ROOT="${HARVEST_ROOT:-}"
# per-ms (default) | global | none
WAIT_MODE="${PIPELINE_WAIT_MODE:-per-ms}"
HTR_ONLY=false
STYLO_ONLY=false
MAX_CONCURRENT="${PIPELINE_MAX_CONCURRENT:-1}"
MIN_IMAGES="${PIPELINE_MIN_IMAGES:-10}"
POLL_SEC="${PIPELINE_POLL_SEC:-300}"
STYLO_EVERY_TICKS="${STYLO_EVERY_TICKS:-6}"
DOC_TYPE="${STREAM_DOC_TYPE:-computus_medieval_latin}"
PROVIDER="${STREAM_PROVIDER:-gemini}"
LLM_MODE="${STREAM_LLM_MODE:-correct}"
case "$LLM_MODE" in
  off|correct) ;;
  *) echo "coerce STREAM_LLM_MODE=$LLM_MODE → correct (autocorrect only)" >&2; LLM_MODE=correct ;;
esac
# On-machine Kraken HTR. LLM, if any, is HTR autocorrect only. Expand is rules.
HTR_COMBINATION="${STREAM_HTR_COMBINATION:-kraken_htr}"
BATCH_SIZE="${STREAM_BATCH_SIZE:-4}"
IDLE_LIMIT="${STREAM_IDLE_LIMIT:-30}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wait-harvest) WAIT_MODE=global; shift ;;
    --wait-manuscript|--wait-per-ms) WAIT_MODE=per-ms; shift ;;
    --htr-only) HTR_ONLY=true; shift ;;
    --stylo-only) STYLO_ONLY=true; shift ;;
    --no-wait) WAIT_MODE=none; shift ;;
    --harvest-root) HARVEST_ROOT="$2"; shift 2 ;;
    --max-concurrent) MAX_CONCURRENT="$2"; shift 2 ;;
    --min-images) MIN_IMAGES="$2"; shift 2 ;;
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

if [[ -z "${JOBS_ROOT:-}" ]]; then
  if [[ -d /mnt/constantinople/seth/latin-ms-workspace/jobs ]]; then
    JOBS_ROOT=/mnt/constantinople/seth/latin-ms-workspace/jobs
  else
    JOBS_ROOT="$HOME/latin-ms-workspace/jobs"
  fi
fi

if [[ -d /mnt/constantinople/seth/Projects/stylometry-r ]]; then
  STYLO_ROOT=/mnt/constantinople/seth/Projects/stylometry-r
elif [[ -d "$HOME/Projects/stylometry-r" ]]; then
  STYLO_ROOT="$HOME/Projects/stylometry-r"
else
  STYLO_ROOT="${STYLO_ROOT:-$HOME/Projects/stylometry-r}"
fi

TSHELL="$ROOT"
VENV=""
for cand in "$TSHELL/.venv-lineation" "$HOME/.venv-lineation" "$HOME/.venv-kraken"; do
  if [[ -x "$cand/bin/python" ]]; then VENV="$cand"; break; fi
done
[[ -n "$VENV" ]] || VENV="$HOME/.venv-kraken"
PY_HTR="$VENV/bin/python"
[[ -x "$PY_HTR" ]] || PY_HTR="$(command -v python3)"

EXPAND_ROOT="${EXPAND_DIPLOMATIC_ROOT:-}"
if [[ -z "$EXPAND_ROOT" ]]; then
  for cand in \
    "$HOME/Projects/expand-diplomatic" \
    /mnt/constantinople/seth/Projects/expand-diplomatic; do
    if [[ -f "$cand/expand_diplomatic/expander.py" ]]; then
      EXPAND_ROOT="$cand"
      break
    fi
  done
fi
[[ -n "$EXPAND_ROOT" ]] || EXPAND_ROOT="$HOME/Projects/expand-diplomatic"

STAMP="${CORPUS_STAMP:-$(date +%Y%m%d)}"
CORPUS_OUT="${CORPUS_OUT:-$STYLO_ROOT/output/computus_web_harvest_corpus_${STAMP}}"
STATE_DIR="$HARVEST_ROOT/htr_pipeline_state"
LOG_DIR="$HARVEST_ROOT/logs"
QUEUE="$HARVEST_ROOT/queues/htr_queue.jsonl"
ACQ_Q="$HARVEST_ROOT/queues/acquire_queue.jsonl"
REG="$HARVEST_ROOT/registry/union_registry_discovered.jsonl"
[[ -f "$REG" ]] || REG="$HARVEST_ROOT/registry/union_registry_validated.jsonl"
[[ -f "$REG" ]] || REG="$ROOT/references/computus-library/web_harvest/union_registry.jsonl"

mkdir -p "$STATE_DIR" "$LOG_DIR" "$HARVEST_ROOT/queues" "$CORPUS_OUT"

LOCK="$HARVEST_ROOT/htr_supervisor.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[post-harvest $(date -Iseconds)] another HTR supervisor holds $LOCK — exiting"
  exit 0
fi

log() { echo "[post-harvest $(date -Iseconds)] $*"; }

count_ms_done() {
  local n=0
  if [[ -d "$HARVEST_ROOT/done" ]]; then
    n=$(find "$HARVEST_ROOT/done" -maxdepth 1 -type f ! -name 'index.jsonl' 2>/dev/null | wc -l | tr -d ' ')
  fi
  if [[ "$n" -eq 0 && -d "$JOBS_ROOT" ]]; then
    n=$(find "$JOBS_ROOT" -maxdepth 3 -path '*/status/acquire.DONE' 2>/dev/null | wc -l | tr -d ' ')
  fi
  echo "${n:-0}"
}

wait_for_first_manuscript() {
  log "waiting for first per-manuscript acquire.DONE under $HARVEST_ROOT/done or jobs/*/status"
  while true; do
    n=$(count_ms_done)
    if [[ "$n" -gt 0 ]]; then
      log "per-manuscript DONE detected (n=$n) — starting incremental HTR"
      return 0
    fi
    # also proceed if full harvest finished with no markers (legacy)
    if [[ -f "$HARVEST_ROOT/logs/DONE" ]]; then
      log "global harvest DONE with no per-ms markers yet; continuing"
      return 0
    fi
    sleep 30
  done
}

wait_for_harvest_global() {
  log "waiting for global harvest DONE under $HARVEST_ROOT/logs"
  while true; do
    if [[ -f "$HARVEST_ROOT/logs/DONE" ]]; then
      log "global harvest DONE detected"
      return 0
    fi
    if grep -ql "DONE harvest_root" "$HARVEST_ROOT"/logs/pipeline_*.log 2>/dev/null; then
      log "harvest DONE detected in pipeline log"
      return 0
    fi
    if [[ -f "$HARVEST_ROOT/reports/COVERAGE_REPORT.md" ]] \
      && [[ -f "$ACQ_Q" ]] \
      && ! pgrep -f "run_web_harvest.sh|discover_sources.py|run_acquire_queue.py" >/dev/null 2>&1; then
      log "harvest appears complete (report + idle workers)"
      return 0
    fi
    sleep 60
  done
}

case "$WAIT_MODE" in
  per-ms) wait_for_first_manuscript ;;
  global) wait_for_harvest_global ;;
  none) log "no wait (WAIT_MODE=none)" ;;
  *) log "unknown WAIT_MODE=$WAIT_MODE — treating as none" ;;
esac

build_htr_queue() {
  log "build reviewed HTR queue (min_images=$MIN_IMAGES, require acquire.DONE)"
  # merge confirmed + needs_review acquire queues when building candidates
  local aq="$ACQ_Q"
  if [[ -f "$HARVEST_ROOT/queues/needs_review_acquire_queue.jsonl" ]]; then
    cat "$ACQ_Q" "$HARVEST_ROOT/queues/needs_review_acquire_queue.jsonl" \
      >"$HARVEST_ROOT/queues/htr_source_acquire_merged.jsonl" 2>/dev/null || true
    aq="$HARVEST_ROOT/queues/htr_source_acquire_merged.jsonl"
  fi
  "$PY" "$SCRIPT_DIR/build_htr_queue.py" \
    --jobs-root "$JOBS_ROOT" \
    --acquire-queue "$aq" \
    --registry "$REG" \
    --out "$QUEUE" \
    --min-images "$MIN_IMAGES" \
    --require-acquire-done
}

alive_pid() {
  local f="$1" p
  [[ -f "$f" ]] || return 1
  p=$(tr -d '[:space:]' < "$f" 2>/dev/null || true)
  [[ -n "$p" ]] || return 1
  kill -0 "$p" 2>/dev/null || return 1
  if [[ -r "/proc/$p/cmdline" ]]; then
    tr '\0' ' ' < "/proc/$p/cmdline" | grep -q watch_transcribe
  fi
}

watcher_running() { alive_pid "$1/status/watch_transcribe.pid"; }

start_watcher() {
  local job="$1" id pid
  id=$(basename "$job")
  mkdir -p "$job"/{logs,status,scripts,01_pages_2500,03_artifacts_2500,transcription_batches,04_expanded,05_stylo}
  cp -f "$TSHELL/scripts/remote_stream_watch_transcribe.py" "$job/scripts/" 2>/dev/null || true
  cp -f "$TSHELL/scripts/computus/htr_watch_policy.py" "$job/scripts/" 2>/dev/null || true
  _combo_lc=$(printf '%s' "$HTR_COMBINATION" | tr '[:upper:]' '[:lower:]')
  case "$_combo_lc" in
    shell|off|none|llm_only)
      log "REFUSE_HTR id=$id combo=$HTR_COMBINATION (LLM-only forbidden)"
      return 1
      ;;
  esac
  nohup env \
    STREAM_JOB_DIR="$job" \
    STREAM_DOC_TYPE="$DOC_TYPE" \
    STREAM_PROVIDER="$PROVIDER" \
    STREAM_LLM_MODE="$LLM_MODE" \
    STREAM_MODEL="${STREAM_MODEL:-}" \
    STREAM_HTR_COMBINATION="$HTR_COMBINATION" \
    STREAM_BATCH_SIZE="$BATCH_SIZE" \
    STREAM_IDLE_LIMIT="$IDLE_LIMIT" \
    STREAM_CONTINUE_ON_LINEATION_FAILURE=0 \
    STREAM_EXPAND=0 \
    STREAM_TRANSCRIPTION_SHELL_ROOT="$TSHELL" \
    STREAM_TRANSCRIPTION_SHELL_VENV="$VENV" \
    STREAM_STYLO_REF="$STYLO_ROOT/output/de_luce_r_rescore/reference_set_medieval_mixed" \
    STREAM_STYLO_RUNNER="$STYLO_ROOT/scripts/run_stylo_target.R" \
    STREAM_STYLO_OUT="$job/05_stylo" \
    EXPAND_DIPLOMATIC_ENABLED=0 \
    TRANSCRIBER_SHELL_EXPAND_DIPLOMATIC=0 \
    EXPAND_DIPLOMATIC_BACKEND=rules \
    EXPAND_DIPLOMATIC_MODEL="${EXPAND_DIPLOMATIC_MODEL:-}" \
    EXPAND_DIPLOMATIC_ROOT="$EXPAND_ROOT" \
    EXPAND_DIPLOMATIC_WHOLE_DOC=1 \
    TRANSCRIBER_SHELL_AUTO_EFFICIENCY=1 \
    TRANSCRIBER_SHELL_REQUIRE_HTR_BEFORE_LLM=1 \
    TRANSCRIBER_SHELL_OLLAMA_KEY_WALL_FALLBACK=0 \
    TRANSCRIBER_SHELL_HTR_PARALLEL=0 \
    TRANSCRIBER_SHELL_LLM_MODE="$LLM_MODE" \
    TRANSCRIBER_SHELL_HTR_COMBINATION="$HTR_COMBINATION" \
    TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH="${TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH:-$HOME/src/gm-htr-r7-full_best.mlmodel}" \
    TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH="${TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH:-$HOME/src/gm-seg.mlmodel}" \
    "$PY_HTR" "$job/scripts/remote_stream_watch_transcribe.py" \
    >> "$job/logs/watch_transcribe.nohup.log" 2>&1 &
  pid=$!
  echo $pid > "$job/status/watch_transcribe.pid"
  date -Iseconds > "$STATE_DIR/${id}.started"
  log "STARTED_HTR id=$id pid=$pid doc_type=$DOC_TYPE llm_mode=$LLM_MODE htr=$HTR_COMBINATION expand=deferred stylo=$job/05_stylo"
}

# Print ready job_ids (not doneish, enough images)
pending_job_ids() {
  "$PY" - "$QUEUE" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(0)
for line in path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if row.get("transcription_doneish"):
        continue
    print(row["job_id"])
PY
}

count_active() {
  local n=0 job
  shopt -s nullglob
  for job in "$JOBS_ROOT"/*/status/watch_transcribe.pid; do
    watcher_running "$(dirname "$(dirname "$job")")" && n=$((n+1))
  done
  shopt -u nullglob
  echo "$n"
}

run_stylo_corpus() {
  log "build stylo corpus → $CORPUS_OUT"
  build_htr_queue
  "$PY" "$SCRIPT_DIR/build_stylo_corpus.py" \
    --htr-queue "$QUEUE" \
    --corpus-out "$CORPUS_OUT" \
    --extract-py "$TSHELL/scripts/extract_ms_text.py" \
    --stylo-runner "$STYLO_ROOT/scripts/run_stylo_target.R" \
    --stylo-ref "$STYLO_ROOT/output/de_luce_r_rescore/reference_set_medieval_mixed" \
    --min-words 100 \
    --min-yaml 5 \
    || log "stylo corpus step returned non-zero (may be partial progress)"
}

if [[ "$STYLO_ONLY" == true ]]; then
  run_stylo_corpus
  exit 0
fi

build_htr_queue

if [[ "$HTR_ONLY" != true ]]; then
  run_stylo_corpus || true
fi

log "HTR supervisor start max=$MAX_CONCURRENT min_img=$MIN_IMAGES corpus=$CORPUS_OUT wait=$WAIT_MODE"
echo $$ > "$HARVEST_ROOT/htr_supervisor.pid"
TICK=0
IDLE_EMPTY=0
while true; do
  # backfill DONE markers for idle complete jobs each tick (cheap + keeps HTR fed)
  bf_args=(--jobs-root "$JOBS_ROOT" --harvest-root "$HARVEST_ROOT" --min-images 5)
  [[ -f "$ACQ_Q" ]] && bf_args+=(--queue "$ACQ_Q")
  [[ -f "$HARVEST_ROOT/queues/needs_review_acquire_queue.jsonl" ]] \
    && bf_args+=(--queue "$HARVEST_ROOT/queues/needs_review_acquire_queue.jsonl")
  "$PY" "$SCRIPT_DIR/backfill_manuscript_done.py" "${bf_args[@]}" >/dev/null 2>&1 || true

  build_htr_queue
  started=0
  pending=0
  while IFS= read -r jid; do
    [[ -z "$jid" ]] && continue
    pending=$((pending+1))
    job="$JOBS_ROOT/$jid"
    if [[ -f "$job/status/skip_print_dump" ]]; then
      continue
    fi
    if [[ -f "$job/status/htr.INCOMPLETE" ]]; then
      continue
    fi
    watcher_running "$job" && continue
    if [[ "$(count_active)" -ge "$MAX_CONCURRENT" ]]; then
      log "THROTTLE active>=$MAX_CONCURRENT ($jid waiting)"
      break
    fi
    start_watcher "$job"
    started=$((started+1))
  done < <(pending_job_ids)

  active=$(count_active)
  done_n=$(ls "$STATE_DIR"/*.done 2>/dev/null | wc -l | tr -d ' ' || echo 0)
  ms_done=$(count_ms_done)
  log "tick pending=$pending active=$active started_now=$started htr_done=$done_n ms_acquire_done=$ms_done"

  # mark doneish from queue
  "$PY" - "$QUEUE" "$STATE_DIR" <<'PY'
import json, sys
from pathlib import Path
q, state = Path(sys.argv[1]), Path(sys.argv[2])
if not q.is_file():
    raise SystemExit(0)
for line in q.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if row.get("transcription_doneish"):
        (state / f"{row['job_id']}.done").write_text("ok\n", encoding="utf-8")
PY

  TICK=$((TICK+1))
  if (( TICK % STYLO_EVERY_TICKS == 0 )) && [[ "$HTR_ONLY" != true ]]; then
    run_stylo_corpus || true
  fi

  # Incremental mode: do not exit while acquire queues still running.
  acq_busy=false
  pgrep -f "run_acquire_queue.py" >/dev/null 2>&1 && acq_busy=true

  if [[ "$pending" -eq 0 && "$active" -eq 0 ]]; then
    if [[ "$acq_busy" == true ]]; then
      IDLE_EMPTY=$((IDLE_EMPTY+1))
      log "HTR idle (no ready manuscripts); acquire still running (empty_ticks=$IDLE_EMPTY)"
    else
      if [[ "$HTR_ONLY" != true ]]; then
        log "all HTR queue jobs doneish + acquire idle — final corpus build"
        run_stylo_corpus || true
      fi
      log "DONE post-harvest corpus=$CORPUS_OUT"
      exit 0
    fi
  else
    IDLE_EMPTY=0
  fi
  sleep "$POLL_SEC"
done
