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
  skipped_dupes=0
  skipped_claimed=0
  # Job-name prefix is configurable so this driver can serve the computus tree
  # too. Hardcoding ctrl_* meant pointing JOBS_ROOT at jobs/ silently matched
  # nothing: the driver reported "pending=0 ... DONE no ready control jobs" and
  # exited in seconds, looking like a completed run rather than a mismatch.
  # ${JOB_PREFIX-ctrl_} without the colon on purpose: ":-" substitutes the
  # default for an EMPTY value too, so JOB_PREFIX="" (meaning "match every
  # job dir", which the computus tree needs since its dirs share no prefix)
  # silently became ctrl_ and matched nothing.
  for job in "$JOBS_ROOT"/${JOB_PREFIX-ctrl_}*; do
    [[ -d "$job" ]] || continue
    [[ -f "$job/status/acquire.DONE" ]] || continue
    # htr.DONE is what the LOCAL watcher writes on completion; the other two are
    # written by the Bridges path and by the full pipeline. Omitting htr.DONE
    # meant a locally-finished manuscript was never recognised as finished: the
    # driver kept re-picking the same first N jobs, each worker started, logged
    # "no pending pages", exited, and got relaunched two minutes later. Six
    # manuscripts completed and then the run sat still for hours at
    # pending=100 active=6 started_now=6 with the GPU at 0%.
    # htr.INCOMPLETE is TERMINAL, not transient. remote_stream_watch_transcribe
    # writes it only from finish_manuscript(), i.e. after pages are exhausted,
    # when YAML+skip coverage came in under 90% because some batches hard-failed.
    # It deliberately refuses to stamp DONE there -- failed batches are not
    # completions -- but the driver did not know the marker existed, so such a
    # job sat in a deadlock: nothing pending so no work to do, no DONE stamp so
    # never skipped, re-picked every two minutes forever. It held the run at
    # 31/100 with six "active" workers and the machine at load 0.44.
    #
    # Partial output is still usable: those manuscripts contribute the pages that
    # did succeed (359 of 445 in the case that exposed this).
    # TERMINAL MARKERS. This list must cover every terminal state the worker can
    # write, or a job in a state we forgot sits in a deadlock: nothing pending so
    # no work to do, no recognised stamp so never skipped, re-picked every cycle
    # forever. That happened twice -- first htr.DONE was missing, then
    # htr.INCOMPLETE -- each time holding the run for hours while reporting
    # healthy ticks.
    #
    # Audited against remote_stream_watch_transcribe.py, which can write:
    #   htr.DONE         completion when llm_mode=off
    #   transcribe.DONE  completion when llm_mode is NOT off (same code path,
    #                    marker_name chosen by LLM_MODE) -- this driver supports
    #                    STREAM_LLM_MODE=correct, so it is reachable here
    #   pipeline.DONE    full-pipeline completion
    #   htr.INCOMPLETE   pages exhausted, coverage under 90% (terminal)
    #   llm.CAP          LLM quota cap -- deliberately NOT terminal: HTR work may
    #                    still be pending, and skipping would abandon it
    # htr_bridges.DONE is written by the Bridges path, not by the worker.
    for marker in htr.DONE transcribe.DONE htr_bridges.DONE pipeline.DONE htr.INCOMPLETE; do
      [[ -f "$job/status/$marker" ]] && continue 2
    done

    # ALIAS DUPLICATES. The harvest registered many manuscripts under both a bare
    # catalogue id (clat_467) and a descriptive one
    # (clat_467_einsiedeln_stiftsbibliothek_29) and acquired both. Recognizing
    # each twice is pure waste: 85 of 237 eligible computus manuscripts are second
    # copies, 24,432 pages' worth, and roughly half of one 12-hour Bridges job
    # went on them before this was noticed.
    #
    # Skip a job when a SIBLING sharing its alias stem is already terminal. The
    # suffix must be descriptive (>=2 underscore-separated segments); a lone short
    # token like `_cod` is a type marker, and matching on it would merge
    # genuinely distinct manuscripts.
    # CLAIMED BY ANOTHER MACHINE. Bridges runs the same job tree from /ocean, so
    # a claim marker keeps the two from recognizing the same manuscript twice --
    # which is exactly how ~28,500 pages of redundant HTR happened.
    #
    # NOT terminal: if the remote run dies the claim must be cleared or the work
    # is never done. Stale claims are therefore expired here rather than trusted
    # forever.
    if [[ -f "$job/status/htr_bridges.CLAIMED" && ! -f "$job/status/htr_bridges.DONE" ]]; then
      _claim_age=$(( $(date +%s) - $(stat -c %Y "$job/status/htr_bridges.CLAIMED" 2>/dev/null || echo 0) ))
      if (( _claim_age < ${CLAIM_TTL_SECONDS:-172800} )); then
        skipped_claimed=$((skipped_claimed+1))
        continue
      fi
      log "claim on $(basename "$job") is $((_claim_age/3600))h old -- expiring it"
      rm -f "$job/status/htr_bridges.CLAIMED"
    fi

    if [[ "${SKIP_ALIAS_DUPES:-1}" == 1 ]]; then
      _base="$(basename "$job")"
      _stem="$(printf '%s' "$_base" | sed -E 's/^([a-z]+_[0-9]+(_[0-9]+)?)(_[a-z][a-z0-9]*_.+)?$/\1/')"
      if [[ -n "$_stem" ]]; then
        _dupe_done=0
        for _sib in "$JOBS_ROOT/$_stem" "$JOBS_ROOT/$_stem"_*; do
          [[ -d "$_sib" ]] || continue
          [[ "$_sib" == "$job" ]] && continue
          [[ "$(basename "$_sib")" == "$_stem"* ]] || continue
          for _m in htr.DONE transcribe.DONE htr_bridges.DONE pipeline.DONE; do
            if [[ -f "$_sib/status/$_m" ]]; then _dupe_done=1; break; fi
          done
          [[ "$_dupe_done" == 1 ]] && break
        done
        if [[ "$_dupe_done" == 1 ]]; then
          skipped_dupes=$((skipped_dupes+1))
          continue
        fi
        # Neither copy finished yet: pick deterministically so both are not
        # recognized in parallel. Prefer the one with MORE images -- the bare
        # catalogue id is often a near-empty stub (1MB against 854MB) -- and
        # break exact ties on the longer name, which is the descriptive id.
        _mine=$(count_images "$job")
        for _sib in "$JOBS_ROOT/$_stem" "$JOBS_ROOT/$_stem"_*; do
          [[ -d "$_sib" ]] || continue
          [[ "$_sib" == "$job" ]] && continue
          [[ "$(basename "$_sib")" == "$_stem"* ]] || continue
          [[ -f "$_sib/status/acquire.DONE" ]] || continue
          _theirs=$(count_images "$_sib")
          if (( _theirs > _mine )) || { (( _theirs == _mine )) &&              [[ ${#_sib} -gt ${#job} ]]; }; then
            skipped_dupes=$((skipped_dupes+1))
            # continue 2, NOT 3. Nesting is: while true (1) -> for job (2) ->
            # for _sib (3). `continue 3` restarts the WHILE loop, skipping the
            # tick log and the sleep, so the driver span silently at full tilt
            # and logged nothing for twelve hours after starting two workers.
            continue 2
          fi
        done
      fi
    fi
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
  # STALL DETECTION. Both deadlocks this driver hit were SILENT: healthy-looking
  # ticks, six "active" workers, no errors, and zero progress for hours. What
  # actually distinguished a working run from a stalled one was whether output
  # was appearing, so measure that and say so.
  #
  # Counting YAML across every job each tick would be expensive, so track the
  # count and only complain when it has not moved for several ticks while workers
  # are supposedly active -- the exact signature of both failures.
  produced=$(find "$JOBS_ROOT" -name '*_transcription.yaml' 2>/dev/null | wc -l | tr -d '[:space:]')
  if [[ "$produced" -eq "${last_produced:--1}" ]]; then
    stall_ticks=$((${stall_ticks:-0} + 1))
  else
    stall_ticks=0
  fi
  last_produced="$produced"
  log "tick pending=$pending active=$active started_now=$started dupes_skipped=$skipped_dupes claimed_skipped=$skipped_claimed acquire_busy=$acq_busy yaml=$produced"
  if [[ "$stall_ticks" -ge 5 && "$active" -gt 0 ]]; then
    log "STALLED: $active worker(s) active but yaml stuck at $produced for $stall_ticks ticks."
    log "STALLED: check a job log for 'no pending pages' -- a terminal marker may"
    log "STALLED: be missing from the skip list above, which deadlocks the driver."
  fi

  if [[ "$pending" -eq 0 && "$active" -eq 0 && "$acq_busy" == false ]]; then
    log "DONE no ready control jobs"
    exit 0
  fi
  sleep "$POLL_SEC"
done
