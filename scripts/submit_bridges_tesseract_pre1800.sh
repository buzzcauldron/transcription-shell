#!/usr/bin/env bash
# Sync transcription-shell + historical-ocr, submit pre-1800 Tesseract fine-tune on Bridges2.
#
#   bash scripts/submit_bridges_tesseract_pre1800.sh
#
# Optional env:
#   TESS_TRAIN_MAX_ITER=100000
#   TESS_TRAIN_MODEL_NAME=lat_pre1800
#   TESS_TRAIN_START_MODEL=Fraktur
set -euo pipefail

SHELL_REPO="${SHELL_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
HIST_REPO="${HISTORICAL_OCR_ROOT:-$HOME/Projects/historical ocr}"
DTN="${BRIDGES_DTN:-bridges2-dtn}"
LOGIN="${BRIDGES_LOGIN:-bridges2}"
SHELL_DEST="${BRIDGES_SHELL_SRC:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
HIST_DEST="${BRIDGES_HISTORICAL_OCR:-/ocean/projects/hum260002p/sstrickland/historical-ocr}"

if [[ ! -d "$HIST_REPO/src/historical_ocr" ]]; then
  echo "error: historical-ocr not found at $HIST_REPO" >&2
  exit 1
fi

echo "[bridges] sync transcription-shell package + scripts"
rsync -avz -e "ssh -o BatchMode=yes" \
  "$SHELL_REPO/src/transcriber_shell/" "${DTN}:${SHELL_DEST}/transcriber_shell/"
rsync -avz -e "ssh -o BatchMode=yes" \
  "$SHELL_REPO/scripts/" "${DTN}:${SHELL_DEST}/scripts/"

echo "[bridges] sync historical-ocr"
rsync -avz -e "ssh -o BatchMode=yes" \
  --exclude '.venv/' --exclude 'jobs/' --exclude 'data/' --exclude 'models/' \
  --exclude '.git/' --exclude '__pycache__/' \
  "$HIST_REPO/" "${DTN}:${HIST_DEST}/"

REMOTE_ENV="export TRANSCRIBER_SHELL_ROOT='$SHELL_DEST' HISTORICAL_OCR_ROOT='$HIST_DEST'"
[[ -n "${TESS_TRAIN_MAX_ITER:-}" ]] && REMOTE_ENV="$REMOTE_ENV TESS_TRAIN_MAX_ITER='$TESS_TRAIN_MAX_ITER'"
[[ -n "${TESS_TRAIN_MODEL_NAME:-}" ]] && REMOTE_ENV="$REMOTE_ENV TESS_TRAIN_MODEL_NAME='$TESS_TRAIN_MODEL_NAME'"
[[ -n "${TESS_TRAIN_START_MODEL:-}" ]] && REMOTE_ENV="$REMOTE_ENV TESS_TRAIN_START_MODEL='$TESS_TRAIN_START_MODEL'"

echo "[bridges] verify historical-ocr venv (run sync_historical_ocr.sh if missing)"
ssh -o BatchMode=yes "$LOGIN" "bash -lc '
  $REMOTE_ENV
  cd \"$HIST_DEST\"
  if [[ -x .venv/bin/historical-ocr ]]; then
    .venv/bin/historical-ocr --version
  else
    echo \"warn: .venv/bin/historical-ocr missing — run scripts/sync_historical_ocr.sh first\" >&2
    exit 1
  fi
'"

echo "[bridges] submit tess-pre1800 (GPU-shared, qos=gpu, 48h)"
JOB=$(ssh -o BatchMode=yes "$LOGIN" "bash -lc '
  $REMOTE_ENV
  cd \"$SHELL_DEST\"
  sbatch --parsable -A hum260002p scripts/bridges_train_tesseract_pre1800.sbatch
'")

echo "[bridges] job id: $JOB"
echo ""
echo "Monitor:"
echo "  ssh $LOGIN squeue -u \$USER"
echo "  ssh $LOGIN tail -f $SHELL_DEST/tess-pre1800-${JOB}.out"
echo ""
echo "Pull model when done:"
echo "  scp $DTN:$SHELL_DEST/models/lat_pre1800.traineddata \"$HIST_REPO/models/\""
