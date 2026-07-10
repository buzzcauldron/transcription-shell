#!/usr/bin/env bash
# Launch chunked strigil acquisition on a remote worker.
#
# Required environment:
#   STREAM_JOB_DIR       Remote job directory
#   STREAM_URL_TEMPLATE  printf-style URL template with one integer slot, e.g.
#                        https://.../bav_pal_lat_1407/%04d
# Optional:
#   STREAM_START         First page index, default 1
#   STREAM_END           Last page index, default 1
#   STREAM_CHUNK_SIZE    Page count per strigil process, default 85
#   STREAM_STRIGIL_DIR   strigil checkout, default ~/Projects/strigil
#   STREAM_WORKERS       strigil workers per chunk, default 6
#   STREAM_MIN_IMAGE     strigil --min-image-size, default 200k

set -euo pipefail

JOB="${STREAM_JOB_DIR:?set STREAM_JOB_DIR}"
URL_TEMPLATE="${STREAM_URL_TEMPLATE:?set STREAM_URL_TEMPLATE}"
START="${STREAM_START:-1}"
END="${STREAM_END:-1}"
CHUNK_SIZE="${STREAM_CHUNK_SIZE:-85}"
STRIGIL_DIR="${STREAM_STRIGIL_DIR:-$HOME/Projects/strigil}"
WORKERS="${STREAM_WORKERS:-6}"
MIN_IMAGE="${STREAM_MIN_IMAGE:-200k}"

mkdir -p "$JOB/00_sources_chunks" "$JOB/logs" "$JOB/status"

chunk=1
first="$START"
while [[ "$first" -le "$END" ]]; do
  last=$((first + CHUNK_SIZE - 1))
  if [[ "$last" -gt "$END" ]]; then
    last="$END"
  fi
  name=$(printf "chunk_%02d" "$chunk")
  out="$JOB/00_sources_chunks/$name"
  mkdir -p "$out"
  nohup bash -lc "cd '$STRIGIL_DIR' && urls=\$(python3 - <<PY
template = '''$URL_TEMPLATE'''
print(' '.join(template % i for i in range($first, $last + 1)))
PY
) && PYTHONPATH='$STRIGIL_DIR' python3 -m strigil.cli --url \$urls --out-dir '$out' --types images --manuscript --min-image-size '$MIN_IMAGE' --no-progress --workers '$WORKERS'" \
    > "$JOB/logs/acquire_${name}.log" 2>&1 &
  echo $! > "$JOB/status/acquire_${name}.pid"
  echo "started $name pages $first-$last pid=$(cat "$JOB/status/acquire_${name}.pid")"
  first=$((last + 1))
  chunk=$((chunk + 1))
done
