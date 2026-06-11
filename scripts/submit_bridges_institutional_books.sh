#!/usr/bin/env bash
# Sync scripts and submit Institutional Books 1.0 corpus build on Bridges2.
#
# Metadata-only (no HF auth):
#   bash scripts/submit_bridges_institutional_books.sh
#
# Include gated OCR text export (after metadata manifest exists):
#   hf auth login   # once, locally
#   INST_BOOKS_EXPORT_TEXT=1 bash scripts/submit_bridges_institutional_books.sh
#
# Text-only pass (reuse manifest.jsonl from a prior metadata job):
#   INST_BOOKS_EXPORT_TEXT=1 INST_BOOKS_EXPORT_TEXT_ONLY=1 bash scripts/submit_bridges_institutional_books.sh
#
# Optional env:
#   INST_BOOKS_PROFILE=pre1800_law_latin_llm
#   INST_BOOKS_MAX_VOLUMES=200
set -euo pipefail

SHELL_REPO="${SHELL_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
DTN="${BRIDGES_DTN:-bridges2-dtn}"
LOGIN="${BRIDGES_LOGIN:-bridges2}"
SHELL_DEST="${BRIDGES_SHELL_SRC:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"

echo "[bridges] sync scripts"
rsync -avz -e "ssh -o BatchMode=yes" \
  "$SHELL_REPO/scripts/" "${DTN}:${SHELL_DEST}/scripts/"

REMOTE_ENV="export TRANSCRIBER_SHELL_ROOT='$SHELL_DEST'"
[[ -n "${INST_BOOKS_PROFILE:-}" ]] && REMOTE_ENV="$REMOTE_ENV INST_BOOKS_PROFILE='$INST_BOOKS_PROFILE'"
[[ -n "${INST_BOOKS_MAX_VOLUMES:-}" ]] && REMOTE_ENV="$REMOTE_ENV INST_BOOKS_MAX_VOLUMES='$INST_BOOKS_MAX_VOLUMES'"
[[ -n "${INST_BOOKS_EXPORT_TEXT:-}" ]] && REMOTE_ENV="$REMOTE_ENV INST_BOOKS_EXPORT_TEXT='$INST_BOOKS_EXPORT_TEXT'"
[[ -n "${INST_BOOKS_EXPORT_TEXT_ONLY:-}" ]] && REMOTE_ENV="$REMOTE_ENV INST_BOOKS_EXPORT_TEXT_ONLY='$INST_BOOKS_EXPORT_TEXT_ONLY'"

HF_TOKEN="${HF_TOKEN:-}"
if [[ -z "$HF_TOKEN" ]]; then
  HF_TOKEN="$(hf auth token 2>/dev/null || true)"
fi
if [[ -n "$HF_TOKEN" ]]; then
  REMOTE_ENV="$REMOTE_ENV HF_TOKEN='$HF_TOKEN'"
elif [[ "${INST_BOOKS_EXPORT_TEXT:-}" == "1" ]]; then
  echo "error: INST_BOOKS_EXPORT_TEXT=1 requires HF_TOKEN or 'hf auth login'" >&2
  echo "  Accept license: https://huggingface.co/datasets/institutional/institutional-books-1.0" >&2
  exit 1
fi

echo "[bridges] submit ibooks-pre1800 (GPU-shared, qos=gpu, 12h)"
JOB=$(ssh -o BatchMode=yes "$LOGIN" "bash -lc '
  $REMOTE_ENV
  cd \"$SHELL_DEST\"
  sbatch --parsable -A hum260002p scripts/bridges_fetch_institutional_books.sbatch
'")

echo "[bridges] job id: $JOB"
echo ""
echo "Monitor:"
echo "  ssh $LOGIN squeue -u \$USER"
echo "  ssh $LOGIN tail -f $SHELL_DEST/ibooks-pre1800-${JOB}.out"
echo ""
echo "Pull manifest when done:"
echo "  scp -r $DTN:$SHELL_DEST/institutional-books-pre1800-lat ./data/"
