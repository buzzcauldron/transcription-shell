#!/usr/bin/env bash
# Sync repos and submit Institutional Books → Internet Archive → Tesseract on Bridges2.
#
#   bash scripts/submit_bridges_institutional_books_ia.sh
#
# Optional (HF page text as line GT — you accepted the gated license):
#   HF_TOKEN=hf_... bash scripts/submit_bridges_institutional_books_ia.sh
#
# Env: IB_LIMIT IB_MAX_PAGES IB_LANGUAGE IB_MAX_YEAR IB_MIN_OCR IB_MODEL_NAME
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

echo "[bridges] sync transcription-shell scripts"
rsync -avz -e "ssh -o BatchMode=yes" \
  "$SHELL_REPO/scripts/" "${DTN}:${SHELL_DEST}/scripts/"

echo "[bridges] sync historical-ocr"
rsync -avz -e "ssh -o BatchMode=yes" \
  --exclude '.venv/' --exclude 'jobs/' --exclude 'data/' --exclude 'models/' \
  --exclude '.git/' --exclude '__pycache__/' \
  "$HIST_REPO/" "${DTN}:${HIST_DEST}/"

REMOTE_ENV="export TRANSCRIBER_SHELL_ROOT='$SHELL_DEST' HISTORICAL_OCR_ROOT='$HIST_DEST'"
for var in IB_LIMIT IB_MAX_PAGES IB_LANGUAGE IB_MAX_YEAR IB_MIN_OCR IB_MODEL_NAME IB_CORPUS_ROOT; do
  [[ -n "${!var:-}" ]] && REMOTE_ENV="$REMOTE_ENV $var='${!var}'"
done

HF_TOKEN="${HF_TOKEN:-$(hf auth token 2>/dev/null || true)}"
[[ -n "$HF_TOKEN" ]] && REMOTE_ENV="$REMOTE_ENV HF_TOKEN='$HF_TOKEN'"

echo "[bridges] submit ibooks-ia (GPU-shared, 24h)"
JOB=$(ssh -o BatchMode=yes "$LOGIN" "bash -lc '
  $REMOTE_ENV
  cd \"$SHELL_DEST\"
  sbatch --parsable -A hum260002p scripts/bridges_fetch_institutional_books_ia.sbatch
'")

echo "[bridges] job id: $JOB"
echo "Monitor: ssh $LOGIN tail -f $SHELL_DEST/ibooks-ia-${JOB}.out"
