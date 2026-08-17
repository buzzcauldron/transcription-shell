#!/usr/bin/env bash
# Expand unexpanded job pages on akdeniz, re-extract stylo texts, re-run stylo.
# Resume-safe. Pin BLAS threads so stylo does not hog the shared box.
set -euo pipefail

JOBS="${JOBS:-$HOME/latin-ms-workspace/jobs}"
TSHELL="${TSHELL:-$HOME/Projects/transcription-shell}"
STYLO="${STYLO:-$HOME/Projects/stylometry-r}"
EXPAND_ROOT="${EXPAND_DIPLOMATIC_ROOT:-$HOME/Projects/expand-diplomatic}"
PY="${EXPAND_PYTHON:-$HOME/Projects/transcription-shell/.venv-lineation/bin/python}"
[[ -x "$PY" ]] || PY="${HOME}/.venv-expand/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"
LOG_DIR="${LOG_DIR:-$HOME/latin-ms-workspace/logs/expand_stylo}"
BATCH_EXPANDED="${STYLO_BATCH_TEXTS:-$STYLO/output/batch_stylo_texts_expanded}"
HIST_OUT="${HIST_CORE_OUT:-$STYLO/output/historical_genre_core_expanded}"
PILOT_TEXT="${STYLO}/output/clat_stylo_pilot/texts"
STATUS_JSON="$LOG_DIR/expand_status.json"
PRIORITY="$LOG_DIR/priority_jobs.txt"

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
export GEMINI_TIMEOUT="${GEMINI_TIMEOUT:-120}"
export GEMINI_RETRY_ATTEMPTS="${GEMINI_RETRY_ATTEMPTS:-3}"
export EXPANDER_MAX_CONCURRENT="${EXPANDER_MAX_CONCURRENT:-8}"
export HIST_CORE_REUSE_PILOT=0
export STYLO_BATCH_TEXTS="$BATCH_EXPANDED"
export HIST_CORE_OUT="$HIST_OUT"
export STYLO_MAX_SLICES="${STYLO_MAX_SLICES:-120}"

mkdir -p "$LOG_DIR" "$BATCH_EXPANDED" "$PILOT_TEXT"

BACKEND="${EXPAND_DIPLOMATIC_BACKEND:-rules}"
EXPAND_ONLY=false
SKIP_HIST_CORE="${SKIP_HIST_CORE:-0}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expand-only) EXPAND_ONLY=true; SKIP_HIST_CORE=1; shift ;;
    --backend) BACKEND="$2"; shift 2 ;;
    *) echo "Unknown: $1" >&2; exit 2 ;;
  esac
done
if [[ "$BACKEND" != "rules" ]]; then
  echo "refusing LLM expand backend=$BACKEND (expand-diplomatic rules only)" >&2
  exit 2
fi
set -a
# shellcheck disable=SC1091
[[ -f "$TSHELL/.env" ]] && source "$TSHELL/.env"
# shellcheck disable=SC1091
[[ -f "$EXPAND_ROOT/.env" ]] && source "$EXPAND_ROOT/.env"
set +a
if [[ "$BACKEND" == "anthropic" && -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ANTHROPIC_API_KEY not set after sourcing .env" >&2
  exit 2
fi
if [[ "$BACKEND" == "groq" && -z "${GROQ_API_KEY:-}" && -z "${TRANSCRIBER_SHELL_GROQ_API_KEY:-}" ]]; then
  echo "GROQ_API_KEY not set after sourcing .env" >&2
  exit 2
fi
if [[ "$BACKEND" == "gemini" && -z "${GEMINI_API_KEY:-}" && -z "${GOOGLE_API_KEY:-}" ]]; then
  echo "GEMINI_API_KEY / GOOGLE_API_KEY not set after sourcing .env" >&2
  exit 2
fi

# Priority: current stylo corpus slugs (batch_stylo_texts names).
{
  ls "$STYLO/output/batch_stylo_texts"/*_latin.txt 2>/dev/null \
    | xargs -n1 basename \
    | sed 's/_latin\.txt$//'
} > "$PRIORITY"

echo "[$(date -Iseconds)] expand start backend=${BACKEND} jobs=$JOBS parallel=${EXPAND_PARALLEL_FILES:-8}"
"$PY" "$TSHELL/scripts/computus/batch_expand_unexpanded.py" \
  --jobs-root "$JOBS" \
  --tshell-src "$TSHELL/src" \
  --expand-root "$EXPAND_ROOT" \
  --priority-file "$PRIORITY" \
  --backend "$BACKEND" \
  --parallel-files "${EXPAND_PARALLEL_FILES:-8}" \
  --model "${EXPAND_DIPLOMATIC_MODEL:-}" \
  --modality "${EXPAND_DIPLOMATIC_MODALITY:-full}" \
  --passes "${EXPAND_DIPLOMATIC_PASSES:-1}" \
  --no-whole-doc \
  --status-json "$STATUS_JSON"

if [[ "$EXPAND_ONLY" == true ]]; then
  echo "[$(date -Iseconds)] expand-only: skip extract/stylo/CORE"
  echo "  expand status: $STATUS_JSON"
  exit 0
fi

echo "[$(date -Iseconds)] extract expanded texts"
while IFS= read -r slug || [[ -n "${slug:-}" ]]; do
  [[ -z "$slug" ]] && continue
  art="$JOBS/$slug/03_artifacts_2500"
  [[ -d "$art" ]] || continue
  out="$BATCH_EXPANDED/${slug}_latin.txt"
  python3 "$TSHELL/scripts/extract_ms_text.py" "$art" "$out" --prefer-expanded \
    || echo "[extract fail] $slug" >&2
done < "$PRIORITY"

# Also extract remaining expanded jobs into harvest corpus tree.
HARVEST_OUT="$STYLO/output/web_harvest_stylo_expanded"
mkdir -p "$HARVEST_OUT/texts"
for art in "$JOBS"/*/03_artifacts_2500; do
  [[ -d "$art" ]] || continue
  slug=$(basename "$(dirname "$art")")
  grep -qx "$slug" "$PRIORITY" && continue
  n_exp=$(find "$(dirname "$art")/04_expanded" -name '*_expanded.txt' 2>/dev/null | wc -l | tr -d ' ')
  [[ "${n_exp:-0}" -ge 5 ]] || continue
  python3 "$TSHELL/scripts/extract_ms_text.py" "$art" \
    "$HARVEST_OUT/texts/${slug}_latin.txt" --prefer-expanded || true
done

# Mirror St. Gall clat extracts into the pilot text dir.
for job in clat_100_st_gall_stiftsbibliothek_732 \
           clat_101_st_gall_stiftsbibliothek_878 \
           clat_102_st_gall_stiftsbibliothek_899; do
  src="$BATCH_EXPANDED/${job}_latin.txt"
  [[ -f "$src" ]] && cp -f "$src" "$PILOT_TEXT/${job}_latin.txt"
done
for job in sb_732_cod sb_878_cod sb_913_cod; do
  src="$BATCH_EXPANDED/${job}_latin.txt"
  [[ -f "$src" ]] && cp -f "$src" "$PILOT_TEXT/${job}_latin.txt"
done

if [[ "${SKIP_HIST_CORE:-0}" == "1" ]]; then
  echo "[$(date -Iseconds)] SKIP_HIST_CORE=1 — not re-locking CORE"
else
echo "[$(date -Iseconds)] stylo historical core → $HIST_OUT"
cd "$STYLO"
bash scripts/develop_historical_core.sh
fi

echo "[$(date -Iseconds)] stylo clat pilot"
bash scripts/run_clat_stylo_pilot.sh || echo "[pilot] returned non-zero" >&2

if [[ -f "$TSHELL/scripts/computus/build_stylo_corpus.py" ]]; then
  QUEUE="${HTR_QUEUE:-$HOME/latin-ms-workspace/computus_lat_queue/htr_queue.jsonl}"
  if [[ -f "$QUEUE" ]]; then
    echo "[$(date -Iseconds)] harvest stylo corpus"
    python3 "$TSHELL/scripts/computus/build_stylo_corpus.py" \
      --htr-queue "$QUEUE" \
      --corpus-out "$HARVEST_OUT" \
      --extract-py "$TSHELL/scripts/extract_ms_text.py" \
      --stylo-runner "$STYLO/scripts/run_stylo_target.R" \
      --stylo-ref "$STYLO/output/de_luce_r_rescore/reference_set_medieval_mixed" \
      --min-words 100 \
      --min-yaml 5 || echo "[harvest stylo] non-zero" >&2
  fi
fi

echo "[$(date -Iseconds)] DONE"
echo "  expand status: $STATUS_JSON"
echo "  expanded texts: $BATCH_EXPANDED"
echo "  hist core: $HIST_OUT"
