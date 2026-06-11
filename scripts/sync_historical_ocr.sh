#!/usr/bin/env bash
# Sync historical-ocr → transcription-shell print presets + Bridges deployment.
#
#   bash scripts/sync_historical_ocr.sh              # presets + rsync + venv
#   bash scripts/sync_historical_ocr.sh --submit     # also resubmit tess-pre1800
#
# Env:
#   HISTORICAL_OCR_ROOT   sibling checkout (auto-detected)
#   BRIDGES_DTN / BRIDGES_LOGIN
set -euo pipefail

SHELL_REPO="${SHELL_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
SUBMIT=0
for arg in "$@"; do
  [[ "$arg" == "--submit" ]] && SUBMIT=1
done

_resolve_hist() {
  if [[ -n "${HISTORICAL_OCR_ROOT:-}" && -d "${HISTORICAL_OCR_ROOT}/document_types/print" ]]; then
    echo "$HISTORICAL_OCR_ROOT"
    return
  fi
  for cand in \
    "$SHELL_REPO/../historical ocr" \
    "$SHELL_REPO/../historical-ocr" \
    "$HOME/Projects/historical ocr" \
    "$HOME/Projects/historical-ocr"; do
    if [[ -d "$cand/document_types/print" ]]; then
      echo "$cand"
      return
    fi
  done
  echo "error: historical-ocr not found" >&2
  exit 1
}

HIST="$(_resolve_hist)"
DTN="${BRIDGES_DTN:-bridges2-dtn}"
LOGIN="${BRIDGES_LOGIN:-bridges2}"
SHELL_DEST="${BRIDGES_SHELL_SRC:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
HIST_DEST="${BRIDGES_HISTORICAL_OCR:-/ocean/projects/hum260002p/sstrickland/historical-ocr}"

echo "[sync] historical-ocr root: $HIST"

echo "[sync] regenerate print_ocr_presets.yaml"
python3 "$SHELL_REPO/scripts/sync_print_ocr_presets_from_historical_ocr.py" \
  --historical-ocr-root "$HIST"

echo "[sync] historical-ocr → Bridges ($HIST_DEST)"
REPO="$HIST" BRIDGES_DTN="$DTN" BRIDGES_HISTORICAL_OCR="$HIST_DEST" \
  bash "$HIST/scripts/sync_to_bridges.sh"

echo "[sync] transcription-shell scripts + print presets → Bridges"
rsync -avz -e "ssh -o BatchMode=yes" \
  "$SHELL_REPO/scripts/" "${DTN}:${SHELL_DEST}/scripts/"
rsync -avz -e "ssh -o BatchMode=yes" \
  "$SHELL_REPO/src/transcriber_shell/htr/" "${DTN}:${SHELL_DEST}/transcriber_shell/htr/"
rsync -avz -e "ssh -o BatchMode=yes" \
  "$SHELL_REPO/src/transcriber_shell/doc_type_apply.py" \
  "${DTN}:${SHELL_DEST}/transcriber_shell/"

echo "[sync] rebuild historical-ocr venv on Bridges login"
ssh -o BatchMode=yes "$LOGIN" "bash -lc '
  set -e
  export HISTORICAL_OCR_ROOT=\"$HIST_DEST\"
  cd \"$HIST_DEST\"
  bash scripts/setup_bridges_venv.sh
'"

if [[ "$SUBMIT" -eq 1 ]]; then
  echo "[sync] submit tess-pre1800"
  HISTORICAL_OCR_ROOT="$HIST" SHELL_REPO="$SHELL_REPO" \
    bash "$SHELL_REPO/scripts/submit_bridges_tesseract_pre1800.sh"
fi

echo "[sync] done"
