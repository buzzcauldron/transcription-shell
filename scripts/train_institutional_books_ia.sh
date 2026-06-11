#!/usr/bin/env bash
# Build a Tesseract training corpus from Institutional Books metadata + Internet Archive scans.
#
# HF metadata (open) filters volumes; page JPEGs come from archive.org IIIF, not the gated HF dump.
# Optional HF page text (text_by_page_*) is used as line GT when authenticated.
#
# Prerequisites:
#   pip install -e ~/Projects/historical\ ocr
#   hf auth login   # optional; improves GT text when gated dataset is accepted
#
# Usage:
#   ./scripts/train_institutional_books_ia.sh fetch
#   ./scripts/train_institutional_books_ia.sh all
#
# Env:
#   IB_CORPUS_ROOT   default ~/src/institutional-books-ia
#   IB_LIMIT         volumes to resolve on IA (default 30)
#   IB_MAX_PAGES     IA pages per volume (default 30)
#   IB_LANGUAGE      ISO 639-3 filter, default lat
#   IB_MAX_YEAR      publication year cap, default 1799 (pre-1800)
#   IB_MIN_OCR       min ocr score, default 80
#   IB_NO_HF_TEXT=1  images only (no HF text_by_page GT)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HIST_REPO="${HISTORICAL_OCR_ROOT:-$HOME/Projects/historical ocr}"
CORPUS="${IB_CORPUS_ROOT:-$HOME/src/institutional-books-ia}"
LIMIT="${IB_LIMIT:-30}"
MAX_PAGES="${IB_MAX_PAGES:-30}"
LANG="${IB_LANGUAGE:-lat}"
MAX_YEAR="${IB_MAX_YEAR:-1799}"
MIN_OCR="${IB_MIN_OCR:-80}"
MODEL="${IB_MODEL_NAME:-lat_ibooks_ia}"
START_MODEL="${IB_START_MODEL:-Fraktur}"

if [[ ! -d "$HIST_REPO/src/historical_ocr" ]]; then
  echo "error: historical-ocr not found at $HIST_REPO" >&2
  exit 1
fi

HF_ARGS=()
[[ "${IB_NO_HF_TEXT:-}" == "1" ]] && HF_ARGS+=(--no-hf-text)

_run_fetch() {
  echo "[ibooks-ia] corpus=$CORPUS limit=$LIMIT lang=$LANG max_year=$MAX_YEAR"
  cd "$HIST_REPO"
  historical-ocr tess fetch \
    --source institutional-books \
    --out "$CORPUS" \
    --limit "$LIMIT" \
    --language "$LANG" \
    --max-year "$MAX_YEAR" \
    --min-ocr-score "$MIN_OCR" \
    --archive-org \
    --max-pages "$MAX_PAGES" \
    "${HF_ARGS[@]}"
}

_run_prepare() {
  cd "$HIST_REPO"
  historical-ocr tess prepare --corpus "$CORPUS" --model "$MODEL"
}

_run_train() {
  local gt="$CORPUS/tesstrain/${MODEL}-ground-truth"
  local out="${IB_MODEL_OUT:-$HIST_REPO/models/${MODEL}.traineddata}"
  if [[ ! -d "$gt" ]] || [[ -z "$(find "$gt" -name '*.png' -print -quit 2>/dev/null)" ]]; then
    echo "error: no line GT in $gt — run fetch + prepare first" >&2
    exit 1
  fi
  cd "$HIST_REPO"
  historical-ocr tess train-gt \
    --ground-truth "$gt" \
    --out "$out" \
    --model "$MODEL" \
    --start-model "$START_MODEL"
  echo "[ibooks-ia] model: $out"
}

cmd="${1:-all}"
case "$cmd" in
  fetch)   _run_fetch ;;
  prepare) _run_prepare ;;
  train)   _run_train ;;
  all)     _run_fetch; _run_prepare; _run_train ;;
  *)
    echo "usage: $0 {fetch|prepare|train|all}" >&2
    exit 1
    ;;
esac
