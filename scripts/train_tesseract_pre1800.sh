#!/usr/bin/env bash
# Fine-tune Tesseract for pre-1800 Latin / Fraktur print OCR.
#
# Corpus prep: transcription-shell (GT4HistOCR + PAGE-XML).
# Training:    historical-ocr sister project (tesstrain wrapper + make traineddata).
#
# Usage:
#   ./scripts/train_tesseract_pre1800.sh prepare
#   ./scripts/train_tesseract_pre1800.sh train
#   ./scripts/train_tesseract_pre1800.sh all
#
# Environment:
#   HISTORICAL_OCR_ROOT   sibling checkout (default: ../historical ocr)
#   HTR_CORPORA_ROOT      default: ~/src/htr-corpora
#   TESS_GT_DIR           default: ~/src/tesseract-pre1800-gt
#   TESS_TRAIN_MODEL      default: $HISTORICAL_OCR_ROOT/models/lat_pre1800.traineddata
#   MODEL_NAME            output lang id (default: lat_pre1800)
#   START_MODEL           base script model (default: Fraktur)
#   MAX_ITERATIONS        default: 100000
#   RATIO_TRAIN           default: 0.99

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

_resolve_historical_ocr_root() {
  if [[ -n "${HISTORICAL_OCR_ROOT:-}" ]]; then
    echo "$HISTORICAL_OCR_ROOT"
    return
  fi
  for cand in \
    "$ROOT/../historical ocr" \
    "$ROOT/../historical-ocr" \
    "$HOME/Projects/historical ocr" \
    "$HOME/Projects/historical-ocr"; do
    if [[ -f "$cand/pyproject.toml" || -f "$cand/src/historical_ocr/cli.py" ]]; then
      echo "$cand"
      return
    fi
  done
  echo ""
}

HISTORICAL_OCR_ROOT="$(_resolve_historical_ocr_root)"
HTR_CORPORA_ROOT="${HTR_CORPORA_ROOT:-$HOME/src/htr-corpora}"
TESS_GT_DIR="${TESS_GT_DIR:-$HOME/src/tesseract-pre1800-gt}"
MODEL_NAME="${MODEL_NAME:-lat_pre1800}"
START_MODEL="${START_MODEL:-Fraktur}"
MAX_ITERATIONS="${MAX_ITERATIONS:-100000}"
RATIO_TRAIN="${RATIO_TRAIN:-0.99}"
TESS_TRAIN_MODEL="${TESS_TRAIN_MODEL:-${HISTORICAL_OCR_ROOT:+$HISTORICAL_OCR_ROOT/models/$MODEL_NAME.traineddata}}"
TESS_TRAIN_MODEL="${TESS_TRAIN_MODEL:-$HOME/src/models/$MODEL_NAME.traineddata}"
TESSTRAIN_ROOT="${TESSTRAIN_ROOT:-$TESS_GT_DIR/tesstrain_repo}"

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
  echo ""
  echo "Commands: prepare | train | all | status"
}

_ensure_historical_ocr() {
  if [[ -z "$HISTORICAL_OCR_ROOT" ]]; then
    echo "error: historical-ocr not found. Clone sibling project, then:" >&2
    echo "  export HISTORICAL_OCR_ROOT=/path/to/historical\\ ocr" >&2
    echo "  cd \"\$HISTORICAL_OCR_ROOT\" && pip install -e ." >&2
    exit 1
  fi
  if ! command -v historical-ocr >/dev/null 2>&1; then
    echo "error: historical-ocr CLI not on PATH — pip install -e \"$HISTORICAL_OCR_ROOT\"" >&2
    exit 1
  fi
}

_resolve_tessdata() {
  if [[ -n "${TESSDATA:-}" && -f "$TESSDATA/${START_MODEL}.traineddata" ]]; then
    echo "$TESSDATA"
    return
  fi
  for cand in \
    /opt/homebrew/share/tessdata/tessdata_best/script \
    /usr/local/share/tessdata/tessdata_best/script \
    /usr/share/tessdata/tessdata_best/script \
    "$TESS_GT_DIR/tessdata_best/script"; do
    if [[ -f "$cand/${START_MODEL}.traineddata" ]]; then
      echo "$cand"
      return
    fi
  done
  echo ""
}

cmd_prepare() {
  echo "==> Preparing ground truth under $TESS_GT_DIR"
  python3 "$ROOT/scripts/prepare_tesseract_ocr_corpus.py" \
    --corpora-root "$HTR_CORPORA_ROOT" \
    --out-dir "$TESS_GT_DIR" \
    --profile pre1800 \
    --symlink
}

cmd_train() {
  _ensure_historical_ocr
  if [[ ! -d "$TESS_GT_DIR/ground-truth" ]] || [[ -z "$(ls -A "$TESS_GT_DIR/ground-truth" 2>/dev/null || true)" ]]; then
    echo "error: no ground truth in $TESS_GT_DIR/ground-truth — run: $0 prepare" >&2
    exit 1
  fi

  TESSDATA_DIR="$(_resolve_tessdata)"
  if [[ -z "$TESSDATA_DIR" ]]; then
    echo "error: ${START_MODEL}.traineddata not found — install tessdata_best/script" >&2
    echo "  macOS: brew install tesseract-lang" >&2
    exit 1
  fi

  if [[ ! -f "$TESSTRAIN_ROOT/Makefile" ]]; then
    echo "==> Cloning tesstrain into $TESSTRAIN_ROOT"
    git clone --depth 1 https://github.com/tesseract-ocr/tesstrain.git "$TESSTRAIN_ROOT"
  fi

  mkdir -p "$(dirname "$TESS_TRAIN_MODEL")"
  echo "==> Fine-tuning via historical-ocr tess train-gt"
  echo "    model=$MODEL_NAME start=$START_MODEL gt=$TESS_GT_DIR/ground-truth"
  historical-ocr tess train-gt \
    --ground-truth "$TESS_GT_DIR/ground-truth" \
    --out "$TESS_TRAIN_MODEL" \
    --model "$MODEL_NAME" \
    --start-model "$START_MODEL" \
    --max-iterations "$MAX_ITERATIONS" \
    --ratio-train "$RATIO_TRAIN" \
    --tesstrain "$TESSTRAIN_ROOT" \
    --tessdata "$TESSDATA_DIR"

  echo ""
  echo "==> Install for transcriber-shell:"
  FINETUNE_DIR="$(dirname "$TESS_TRAIN_MODEL")/tessdata"
  mkdir -p "$FINETUNE_DIR"
  cp "$TESS_TRAIN_MODEL" "$FINETUNE_DIR/${MODEL_NAME}.traineddata"
  echo "  export TESSDATA_PREFIX=$FINETUNE_DIR"
  echo "  export TRANSCRIBER_SHELL_TESSERACT_LANG=$MODEL_NAME"
  echo "  export TRANSCRIBER_SHELL_TESSERACT_ENABLED=true"
}

cmd_status() {
  echo "HISTORICAL_OCR_ROOT=${HISTORICAL_OCR_ROOT:-not found}"
  echo "HTR_CORPORA_ROOT=$HTR_CORPORA_ROOT"
  echo "TESS_GT_DIR=$TESS_GT_DIR"
  echo "TESS_TRAIN_MODEL=$TESS_TRAIN_MODEL"
  echo "MODEL_NAME=$MODEL_NAME START_MODEL=$START_MODEL"
  if [[ -f "$TESS_GT_DIR/stats.json" ]]; then
    python3 -c "import json, pathlib; d=json.loads(pathlib.Path('$TESS_GT_DIR/stats.json').read_text()); print('GT lines:', d.get('lines_written'))"
  fi
  if [[ -f "$TESS_TRAIN_MODEL" ]]; then
    ls -la "$TESS_TRAIN_MODEL"
  fi
}

ACTION="${1:-}"
case "$ACTION" in
  prepare) cmd_prepare ;;
  train)   cmd_train ;;
  all)     cmd_prepare; cmd_train ;;
  status)  cmd_status ;;
  -h|--help|help|"") usage ;;
  *) echo "unknown command: $ACTION" >&2; usage; exit 1 ;;
esac
