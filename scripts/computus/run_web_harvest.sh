#!/usr/bin/env bash
# Launch / resume the full computus web harvest on Akdeniz (or local).
#
# Stages:
#   1. build union registry
#   2. validate existing candidate URLs
#   3. discover Archive.org candidates for unresolved records
#   4. build structured acquire queue (JSONL)
#   5. run strigil acquire (confirmed only) with host caps
#   6. write coverage audit
#
# Usage (on akdeniz, from transcription-shell checkout):
#   bash scripts/computus/run_web_harvest.sh
#   bash scripts/computus/run_web_harvest.sh --discover-only
#   bash scripts/computus/run_web_harvest.sh --acquire-only
#   bash scripts/computus/run_web_harvest.sh --gallica-retry
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PY="${PYTHON:-python3}"
HARVEST_ROOT="${HARVEST_ROOT:-}"
DISCOVER_ONLY=false
ACQUIRE_ONLY=false
GALLICA_RETRY=false
LIMIT_VALIDATE="${LIMIT_VALIDATE:-0}"
LIMIT_DISCOVER="${LIMIT_DISCOVER:-0}"
LIMIT_ACQUIRE="${LIMIT_ACQUIRE:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --discover-only) DISCOVER_ONLY=true; shift ;;
    --acquire-only) ACQUIRE_ONLY=true; shift ;;
    --gallica-retry) GALLICA_RETRY=true; shift ;;
    --harvest-root) HARVEST_ROOT="$2"; shift 2 ;;
    --limit-validate) LIMIT_VALIDATE="$2"; shift 2 ;;
    --limit-discover) LIMIT_DISCOVER="$2"; shift 2 ;;
    --limit-acquire) LIMIT_ACQUIRE="$2"; shift 2 ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

# Prefer constantinople on akdeniz
if [[ -z "$HARVEST_ROOT" ]]; then
  if [[ -d /mnt/constantinople/seth/latin-ms-workspace ]]; then
    HARVEST_ROOT=/mnt/constantinople/seth/latin-ms-workspace/computus_web_harvest
  else
    HARVEST_ROOT="$ROOT/references/computus-library/web_harvest"
  fi
fi
mkdir -p "$HARVEST_ROOT"/{logs,queues,registry,reports}

REG_DIR="$HARVEST_ROOT/registry"
OUT_BASE="$ROOT/references/computus-library/web_harvest"
mkdir -p "$OUT_BASE"

if [[ -d /mnt/constantinople/seth/latin-ms-workspace/jobs ]]; then
  JOBS_ROOT=/mnt/constantinople/seth/latin-ms-workspace/jobs
else
  JOBS_ROOT="${JOBS_ROOT:-$HOME/latin-ms-workspace/jobs}"
fi
mkdir -p "$JOBS_ROOT"

if [[ -d /mnt/constantinople/seth/Projects/strigil ]]; then
  STRIGIL_DIR=/mnt/constantinople/seth/Projects/strigil
elif [[ -d "$HOME/Projects/strigil" ]]; then
  STRIGIL_DIR="$HOME/Projects/strigil"
else
  STRIGIL_DIR="${STRIGIL_DIR:-$HOME/Projects/strigil}"
fi
if [[ -x "$HOME/.venv-strigil/bin/python" ]]; then
  STRIGIL_PY="$HOME/.venv-strigil/bin/python"
else
  STRIGIL_PY="$PY"
fi

COHORT="/Users/halxiii/Projects/stylometry-r/scripts/historical_cohort_decisions.csv"
if [[ ! -f "$COHORT" ]]; then
  COHORT="$ROOT/../stylometry-r/scripts/historical_cohort_decisions.csv"
fi
if [[ ! -f "$COHORT" && -f "$HARVEST_ROOT/historical_cohort_decisions.csv" ]]; then
  COHORT="$HARVEST_ROOT/historical_cohort_decisions.csv"
fi

log() { echo "[web-harvest $(date -Iseconds)] $*"; }

cd "$ROOT"

if [[ "$ACQUIRE_ONLY" != true ]]; then
  log "build union registry"
  "$PY" scripts/computus/build_union_registry.py \
    --clat "$ROOT/references/computus-library/computus_lat_ms-catalog.json" \
    --manifest "$ROOT/references/computus-library/manifest.json" \
    --cohort "$COHORT" \
    --out-dir "$OUT_BASE"
  cp -a "$OUT_BASE/union_registry.jsonl" "$REG_DIR/union_registry.jsonl"
  cp -a "$OUT_BASE/union_registry_summary.json" "$REG_DIR/union_registry_summary.json" 2>/dev/null || true

  log "validate existing candidate URLs"
  val_args=(--registry "$REG_DIR/union_registry.jsonl" --out "$REG_DIR/union_registry_validated.jsonl" --workers 1)
  if [[ "$LIMIT_VALIDATE" != "0" ]]; then
    val_args+=(--limit "$LIMIT_VALIDATE")
  fi
  "$PY" scripts/computus/discover_sources.py "${val_args[@]}"

  log "discover repository adapters + Archive.org for unresolved"
  disc_args=(
    --registry "$REG_DIR/union_registry_validated.jsonl"
    --out "$REG_DIR/union_registry_discovered.jsonl"
    --discover
    --workers 1
    --only-status needs_discovery not_digitized_unknown url_failed needs_review has_url pending
  )
  if [[ "$LIMIT_DISCOVER" != "0" ]]; then
    disc_args+=(--limit "$LIMIT_DISCOVER")
  fi
  "$PY" scripts/computus/discover_sources.py "${disc_args[@]}"

  log "build acquire queue"
  "$PY" scripts/computus/build_acquire_queue.py \
    --registry "$REG_DIR/union_registry_discovered.jsonl" \
    --out "$HARVEST_ROOT/queues/acquire_queue.jsonl"
fi

if [[ "$DISCOVER_ONLY" == true ]]; then
  log "discover-only complete"
  "$PY" scripts/computus/audit_coverage.py \
    --registry "$REG_DIR/union_registry_discovered.jsonl" \
    --jobs-root "$JOBS_ROOT" \
    --out-dir "$HARVEST_ROOT/reports"
  exit 0
fi

if [[ ! -f "$HARVEST_ROOT/queues/acquire_queue.jsonl" ]]; then
  echo "missing queue; run without --acquire-only first" >&2
  exit 1
fi

# Prefer venv-strigil for acquire (strigil + its deps)
if [[ -x "$HOME/.venv-strigil/bin/python" ]]; then
  PY_ACQ="$HOME/.venv-strigil/bin/python"
else
  PY_ACQ="$STRIGIL_PY"
fi
log "run image acquisition via strigil (confirmed only)"
acq_args=(
  --queue "$HARVEST_ROOT/queues/acquire_queue.jsonl"
  --jobs-root "$JOBS_ROOT"
  --strigil-dir "$STRIGIL_DIR"
  --python "$PY_ACQ"
  --global-concurrency "${ACQUIRE_GLOBAL_CONCURRENCY:-6}"
  --strigil-workers "${STRIGIL_WORKERS:-8}"
  --harvest-root "$HARVEST_ROOT"
)
if [[ "$GALLICA_RETRY" == true ]]; then
  acq_args+=(--retry-hosts gallica.bnf.fr --global-concurrency 1)
fi
if [[ "$LIMIT_ACQUIRE" != "0" ]]; then
  acq_args+=(--limit "$LIMIT_ACQUIRE")
fi
"$PY_ACQ" "$ROOT/scripts/computus/run_acquire_queue.py" "${acq_args[@]}" \
  >"$HARVEST_ROOT/logs/acquire_$(date +%Y%m%dT%H%M%S).log" 2>&1

REG_FOR_AUDIT="$REG_DIR/union_registry_discovered.jsonl"
if [[ ! -f "$REG_FOR_AUDIT" ]]; then
  REG_FOR_AUDIT="$OUT_BASE/union_registry.jsonl"
fi
log "sync download status into registry"
"$PY" scripts/computus/update_download_status.py \
  --registry "$REG_FOR_AUDIT" \
  --jobs-root "$JOBS_ROOT" \
  --out "$REG_DIR/union_registry_with_downloads.jsonl"
REG_AUDITED="$REG_DIR/union_registry_with_downloads.jsonl"

log "coverage audit"
q_args=()
for q in "$HARVEST_ROOT/queues/acquire_queue.jsonl" \
         "$HARVEST_ROOT/queues/needs_review_acquire_queue.jsonl"; do
  [[ -f "$q" ]] && q_args+=(--queue "$q")
done
"$PY" scripts/computus/audit_coverage.py \
  --registry "$REG_AUDITED" \
  --jobs-root "$JOBS_ROOT" \
  --out-dir "$HARVEST_ROOT/reports" \
  "${q_args[@]}"

log "repository sample validation"
"$PY" scripts/computus/validate_repository_samples.py \
  --jobs-root "$JOBS_ROOT" \
  --out-dir "$HARVEST_ROOT/reports" \
  "${q_args[@]}"

# mirror reports into repo tree when writable
if [[ -w "$OUT_BASE" ]]; then
  mkdir -p "$OUT_BASE/reports"
  cp -a "$HARVEST_ROOT/reports/." "$OUT_BASE/reports/"
  cp -a "$REG_AUDITED" "$OUT_BASE/" 2>/dev/null || true
fi

# Signal for post-harvest waiters
: >"$HARVEST_ROOT/logs/DONE"
echo "DONE $(date -Iseconds) harvest_root=$HARVEST_ROOT" | tee -a "$HARVEST_ROOT/logs/DONE"
log "DONE harvest_root=$HARVEST_ROOT reports=$HARVEST_ROOT/reports"

# Optional chain: HTR + stylo corpus after harvest (set CHAIN_POST_HARVEST=1)
if [[ "${CHAIN_POST_HARVEST:-0}" == "1" ]]; then
  log "chaining post-harvest HTR+stylo (CHAIN_POST_HARVEST=1)"
  nohup bash "$SCRIPT_DIR/run_post_harvest_pipeline.sh" \
    --harvest-root "$HARVEST_ROOT" \
    --no-wait \
    >>"$HARVEST_ROOT/logs/post_harvest_$(date +%Y%m%dT%H%M%S).log" 2>&1 &
  echo $! >"$HARVEST_ROOT/post_harvest.pid"
  log "post_harvest pid=$(cat "$HARVEST_ROOT/post_harvest.pid") log=$HARVEST_ROOT/logs/"
fi
