#!/bin/bash
#SBATCH -J tess-pre1800
#SBATCH -p GPU-shared
#SBATCH --qos=gpu
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --cpus-per-task=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/tess-pre1800-%j.out
# Fine-tune Tesseract for pre-1800 print (GT4HistOCR) via historical-ocr tess train-gt.
set -euo pipefail

SHELL_ROOT="${TRANSCRIBER_SHELL_ROOT:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
HIST_ROOT="${HISTORICAL_OCR_ROOT:-/ocean/projects/hum260002p/sstrickland/historical-ocr}"
CORPORA="${HTR_CORPORA_ROOT:-$SHELL_ROOT/htr-corpora}"
GT_DIR="${TESS_GT_DIR:-$SHELL_ROOT/tesseract-pre1800-gt}"
OUT="${TESS_TRAIN_MODEL:-$SHELL_ROOT/models/lat_pre1800.traineddata}"
MODEL_NAME="${TESS_TRAIN_MODEL_NAME:-lat_pre1800}"
START_MODEL="${TESS_TRAIN_START_MODEL:-Fraktur}"
MAX_ITER="${TESS_TRAIN_MAX_ITER:-100000}"
VENV="${HISTORICAL_OCR_VENV:-$HIST_ROOT/.venv}"
TESSTRAIN="${TESS_TRAIN_REPO:-$GT_DIR/tesstrain_repo}"
TESSDATA_ROOT="${TESS_TRAIN_TESSDATA:-$GT_DIR/tessdata_best}"

echo "[pre1800] shell=$SHELL_ROOT hist=$HIST_ROOT"
echo "[pre1800] corpora=$CORPORA gt=$GT_DIR out=$OUT"

# Use historical-ocr Bridges venv (rebuilt by scripts/sync_historical_ocr.sh).
if [[ ! -x "$VENV/bin/historical-ocr" ]]; then
  echo "[pre1800] venv missing historical-ocr CLI — run sync_historical_ocr.sh on login" >&2
  # shellcheck disable=SC1091
  source "$HIST_ROOT/scripts/bridges_load_python.sh"
  rm -rf "$VENV"
  "$BRIDGES_PYTHON3" -m venv "$VENV"
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  unset PYTHONPATH
  pip install -q -U pip setuptools wheel
  pip install -q -e "$HIST_ROOT" Pillow pyyaml pytesseract httpx datasets huggingface_hub
else
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  unset PYTHONPATH
fi

GT4="$CORPORA/gt4histocr"
if [[ ! -d "$GT4/Kallimachos" && -f "$GT4/GT4HistOCR.tar" ]]; then
  echo "[pre1800] extracting GT4HistOCR.tar (4 GB, ~10-20 min)"
  tar xf "$GT4/GT4HistOCR.tar" -C "$GT4" --strip-components=1
  touch "$GT4/.done"
fi
if [[ ! -d "$GT4/Kallimachos" && ! -d "$GT4/EarlyModernLatin" ]]; then
  echo "ERROR: GT4HistOCR missing at $GT4" >&2
  echo "  On Bridges login: cd $SHELL_ROOT && SKIP_LARGE=0 bash scripts/download_htr_corpora.sh" >&2
  exit 1
fi

echo "[pre1800] prepare ground truth"
python3 "$SHELL_ROOT/scripts/prepare_tesseract_ocr_corpus.py" \
  --corpora-root "$CORPORA" \
  --out-dir "$GT_DIR" \
  --profile pre1800 \
  --symlink

N_GT=$(find "$GT_DIR/ground-truth" -name '*.png' 2>/dev/null | wc -l)
echo "[pre1800] ground_truth_lines=$N_GT"
if [[ "$N_GT" -lt 100 ]]; then
  echo "ERROR: need >= 100 line pairs" >&2
  exit 1
fi

mkdir -p "$TESSDATA_ROOT/script"
_tess_dl() {
  local dest="$1" url="$2"
  if [[ ! -f "$dest" ]]; then
    echo "[pre1800] download $(basename "$dest")"
    curl -fsSL -o "$dest" "$url"
  fi
}
_tess_dl "$TESSDATA_ROOT/eng.traineddata" \
  "https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata"
_tess_dl "$TESSDATA_ROOT/lat.traineddata" \
  "https://github.com/tesseract-ocr/tessdata_best/raw/main/lat.traineddata"
_tess_dl "$TESSDATA_ROOT/script/${START_MODEL}.traineddata" \
  "https://github.com/tesseract-ocr/tessdata_best/raw/main/script/${START_MODEL}.traineddata"
# tesstrain lstmf step needs eng in the same TESSDATA dir as START_MODEL
ln -sf "../eng.traineddata" "$TESSDATA_ROOT/script/eng.traineddata"
export TESSDATA_PREFIX="$TESSDATA_ROOT/script"

if [[ ! -f "$TESSTRAIN/Makefile" ]]; then
  echo "[pre1800] clone tesstrain → $TESSTRAIN"
  git clone --depth 1 https://github.com/tesseract-ocr/tesstrain.git "$TESSTRAIN"
fi

mkdir -p "$(dirname "$OUT")"
cd "$HIST_ROOT"
historical-ocr tess train-gt \
  --ground-truth "$GT_DIR/ground-truth" \
  --out "$OUT" \
  --model "$MODEL_NAME" \
  --start-model "$START_MODEL" \
  --max-iterations "$MAX_ITER" \
  --ratio-train 0.99 \
  --tesstrain "$TESSTRAIN" \
  --tessdata "$TESSDATA_ROOT/script"

mkdir -p "$SHELL_ROOT/models/tessdata"
cp "$OUT" "$SHELL_ROOT/models/tessdata/${MODEL_NAME}.traineddata"
echo "[pre1800] done: $OUT"
echo "[pre1800] inference: export TESSDATA_PREFIX=$SHELL_ROOT/models/tessdata"
echo "[pre1800] inference: export TRANSCRIBER_SHELL_TESSERACT_LANG=${MODEL_NAME}+lat+frk+eng"
