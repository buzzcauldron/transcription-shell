#!/usr/bin/env bash
# Launch the standard remote streaming manuscript workflow.
#
# Example:
#   STREAM_REMOTE=akdeniz \
#   STREAM_JOB_ID=pal_lat_1407 \
#   STREAM_URL_TEMPLATE='https://digi.ub.uni-heidelberg.de/diglit/bav_pal_lat_1407/%04d' \
#   STREAM_START=1 STREAM_END=339 \
#   STREAM_DOC_TYPE=computus_medieval_latin \
#   STREAM_TARGET_SLUG=pal_lat_1407_partial \
#   bash scripts/remote_stream_launch.sh

set -euo pipefail

REMOTE="${STREAM_REMOTE:-akdeniz}"
JOB_ID="${STREAM_JOB_ID:?set STREAM_JOB_ID}"
JOB_DIR="${STREAM_JOB_DIR:-/home/seth/latin-ms-workspace/jobs/$JOB_ID}"
REMOTE_SCRIPTS="$JOB_DIR/scripts"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${STREAM_URL_TEMPLATE:=}"
: "${STREAM_SOURCE_URL:=}"
: "${STREAM_START:=1}"
: "${STREAM_END:=1}"
: "${STREAM_DOC_TYPE:=computus_medieval_latin}"
: "${STREAM_PROVIDER:=gemini}"
: "${STREAM_TARGET_SLUG:=${JOB_ID}_partial}"
: "${STREAM_STYLO_OUT:=/home/seth/Projects/stylometry-r/output/${JOB_ID}_partial}"
: "${STREAM_CHUNK_SIZE:=85}"
: "${STREAM_BATCH_SIZE:=8}"
: "${STREAM_IMAGE_NAME_CONTAINS:=}"

ssh -n "$REMOTE" "mkdir -p '$REMOTE_SCRIPTS' '$JOB_DIR/logs' '$JOB_DIR/status'"
rsync -az \
  "$LOCAL_DIR/remote_stream_acquire_chunks.sh" \
  "$LOCAL_DIR/remote_stream_acquire_url.sh" \
  "$LOCAL_DIR/remote_stream_watch_transcribe.py" \
  "$LOCAL_DIR/remote_stream_watch_partial_stylo.py" \
  "$REMOTE:$REMOTE_SCRIPTS/"
ssh -n "$REMOTE" "chmod +x '$REMOTE_SCRIPTS'/remote_stream_*"

remote_env=(
  "STREAM_JOB_DIR='$JOB_DIR'"
  "STREAM_URL_TEMPLATE='$STREAM_URL_TEMPLATE'"
  "STREAM_SOURCE_URL='$STREAM_SOURCE_URL'"
  "STREAM_START='$STREAM_START'"
  "STREAM_END='$STREAM_END'"
  "STREAM_CHUNK_SIZE='$STREAM_CHUNK_SIZE'"
  "STREAM_DOC_TYPE='$STREAM_DOC_TYPE'"
  "STREAM_PROVIDER='$STREAM_PROVIDER'"
  "STREAM_BATCH_SIZE='$STREAM_BATCH_SIZE'"
  "STREAM_TARGET_SLUG='$STREAM_TARGET_SLUG'"
  "STREAM_STYLO_OUT='$STREAM_STYLO_OUT'"
  "STREAM_IMAGE_NAME_CONTAINS='$STREAM_IMAGE_NAME_CONTAINS'"
)

env_line="${remote_env[*]}"

if [[ -n "$STREAM_SOURCE_URL" ]]; then
  ssh -n "$REMOTE" "cd '$JOB_DIR' && $env_line '$REMOTE_SCRIPTS/remote_stream_acquire_url.sh'"
elif [[ -n "$STREAM_URL_TEMPLATE" ]]; then
  ssh -n "$REMOTE" "cd '$JOB_DIR' && $env_line '$REMOTE_SCRIPTS/remote_stream_acquire_chunks.sh'"
else
  echo "Set STREAM_SOURCE_URL (IIIF/landing page) or STREAM_URL_TEMPLATE (page range)." >&2
  exit 1
fi
ssh -n "$REMOTE" "screen -dmS '${JOB_ID}_tw' bash -c '$env_line exec \"$REMOTE_SCRIPTS/remote_stream_watch_transcribe.py\" > \"$JOB_DIR/logs/watch_transcribe.nohup.log\" 2>&1'"
ssh -n "$REMOTE" "screen -dmS '${JOB_ID}_ps' bash -c '$env_line exec \"$REMOTE_SCRIPTS/remote_stream_watch_partial_stylo.py\" > \"$JOB_DIR/logs/watch_partial_stylo.nohup.log\" 2>&1'"

ssh -n "$REMOTE" "cd '$JOB_DIR' && ps -u \"\$USER\" -o pid,etime,pcpu,pmem,command | rg '$JOB_ID|strigil|watch_|transcriber-shell|Rscript' || true"
