#!/usr/bin/env bash
# Launch a single strigil acquisition from one manifest or landing-page URL.
#
# Required environment:
#   STREAM_JOB_DIR
#   STREAM_SOURCE_URL
# Optional:
#   STREAM_STRIGIL_DIR   default ~/Projects/strigil
#   STREAM_WORKERS       default 6
#   STREAM_MIN_IMAGE     default 200k
#   STREAM_STRIGIL_FLAGS extra flags (e.g. --js)

set -euo pipefail

JOB="${STREAM_JOB_DIR:?set STREAM_JOB_DIR}"
URL="${STREAM_SOURCE_URL:?set STREAM_SOURCE_URL}"
STRIGIL_DIR="${STREAM_STRIGIL_DIR:-$HOME/Projects/strigil}"
WORKERS="${STREAM_WORKERS:-6}"
MIN_IMAGE="${STREAM_MIN_IMAGE:-200k}"
EXTRA_FLAGS="${STREAM_STRIGIL_FLAGS:-}"

mkdir -p "$JOB/00_sources_chunks/full" "$JOB/logs" "$JOB/status"

nohup bash -lc "cd '$STRIGIL_DIR' && PYTHONPATH='$STRIGIL_DIR' python3 -m strigil.cli \
  --url '$URL' \
  --out-dir '$JOB/00_sources_chunks/full' \
  --types images \
  --manuscript \
  --min-image-size '$MIN_IMAGE' \
  --no-progress \
  --workers '$WORKERS' \
  $EXTRA_FLAGS" \
  > "$JOB/logs/acquire_full.log" 2>&1 &
echo $! > "$JOB/status/acquire_full.pid"
echo "started full acquire pid=$(cat "$JOB/status/acquire_full.pid") url=$URL"
