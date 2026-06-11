#!/bin/bash
#SBATCH -J ibooks-ia
#SBATCH -p GPU-shared
#SBATCH --qos=gpu
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --cpus-per-task=5
#SBATCH -t 24:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/ibooks-ia-%j.out
# Institutional Books → Internet Archive page scans → tesstrain line GT.
set -euo pipefail

SHELL_ROOT="${TRANSCRIBER_SHELL_ROOT:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
HIST_ROOT="${HISTORICAL_OCR_ROOT:-/ocean/projects/hum260002p/sstrickland/historical-ocr}"
CORPUS="${IB_CORPUS_ROOT:-$SHELL_ROOT/institutional-books-ia}"
LIMIT="${IB_LIMIT:-20}"
MAX_PAGES="${IB_MAX_PAGES:-30}"
LANG="${IB_LANGUAGE:-lat}"
MAX_YEAR="${IB_MAX_YEAR:-1799}"
MIN_OCR="${IB_MIN_OCR:-80}"
MODEL="${IB_MODEL_NAME:-lat_ibooks_ia}"
VENV="${HISTORICAL_OCR_VENV:-$HIST_ROOT/.venv}"

echo "[ibooks-ia] shell=$SHELL_ROOT hist=$HIST_ROOT corpus=$CORPUS"

# shellcheck disable=SC1091
source "$SHELL_ROOT/scripts/bridges_prep_env.sh"
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PY_RUN" -m venv "$VENV"
fi
source "$VENV/bin/activate"
unset PYTHONPATH
pip install -q -U pip
pip install -q -e "$HIST_ROOT" datasets huggingface_hub httpx Pillow pyyaml pytesseract

export IB_CORPUS_ROOT="$CORPUS" IB_LIMIT="$LIMIT" IB_MAX_PAGES="$MAX_PAGES"
export IB_LANGUAGE="$LANG" IB_MAX_YEAR="$MAX_YEAR" IB_MIN_OCR="$MIN_OCR"
export IB_MODEL_NAME="$MODEL" IB_MODEL_OUT="$SHELL_ROOT/models/${MODEL}.traineddata"
export HISTORICAL_OCR_ROOT="$HIST_ROOT"

if [[ -z "${HF_TOKEN:-}" && -z "${HUGGING_FACE_HUB_TOKEN:-}" ]]; then
  echo "[ibooks-ia] no HF_TOKEN — IA images only (weak line GT)"
  export IB_NO_HF_TEXT=1
else
  echo "[ibooks-ia] HF_TOKEN set — pairing IA scans with HF text_by_page"
fi

bash "$SHELL_ROOT/scripts/train_institutional_books_ia.sh" all

mkdir -p "$SHELL_ROOT/models/tessdata"
if [[ -f "$IB_MODEL_OUT" ]]; then
  cp "$IB_MODEL_OUT" "$SHELL_ROOT/models/tessdata/${MODEL}.traineddata"
  echo "[ibooks-ia] tessdata: $SHELL_ROOT/models/tessdata/${MODEL}.traineddata"
fi
echo "[ibooks-ia] done"
