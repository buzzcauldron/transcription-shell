#!/usr/bin/env bash
# Remediate common Bridges training failures (idempotent). For automation use.
#
#   bash scripts/bridges_training_automation_remediate.sh
#   bash scripts/bridges_training_automation_remediate.sh --dry-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SHELL_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
LOGIN="${BRIDGES_LOGIN:-bridges2}"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

run() {
  if [[ "$DRY" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    echo "[remediate] $*"
    "$@"
  fi
}

echo "[remediate] running health check first..."
if bash "$SCRIPT_DIR/bridges_training_automation_check.sh"; then
  echo "[remediate] nothing to do"
  exit 0
fi

echo "[remediate] cancelling DependencyNeverSatisfied orphans"
ssh -o BatchMode=yes "$LOGIN" 'squeue -u $USER -h -o "%i %r" | awk "$2==\"(DependencyNeverSatisfied)\"" {print $1}' \
  | while read -r jid; do
    [[ -z "$jid" ]] && continue
    run ssh -o BatchMode=yes "$LOGIN" "scancel $jid" || true
  done

# Sync scripts + fix venvs before resubmit
run bash "$SCRIPT_DIR/sync_scripts_to_bridges.sh" 2>/dev/null || \
  rsync -avz -e "ssh -o BatchMode=yes" "$SCRIPT_DIR/" "${BRIDGES_DTN:-bridges2-dtn}:${BRIDGES_SHELL_SRC:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}/scripts/"

run ssh -o BatchMode=yes "$LOGIN" "bash /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/scripts/fix_bridges_venv_paths.sh" || true

# historical-ocr venv for tess-pre1800
HIST_REPO="${HISTORICAL_OCR_ROOT:-$SHELL_REPO/../historical-ocr}"
if [[ -d "$HIST_REPO" ]]; then
  run bash "$SCRIPT_DIR/sync_historical_ocr.sh" || true
fi

# Resubmit HTR chain if r6 not running
if ! ssh -o BatchMode=yes "$LOGIN" "squeue -u \$USER -h -o '%j' | grep -q htr-r6-core"; then
  run ssh -o BatchMode=yes "$LOGIN" "bash /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/scripts/bridges_start.sh"
fi

# Resubmit tess-pre1800 if not running and no model yet
if ! ssh -o BatchMode=yes "$LOGIN" "test -f /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/models/lat_pre1800.traineddata"; then
  if ! ssh -o BatchMode=yes "$LOGIN" "squeue -u \$USER -h -o '%j' | grep -q tess-pre1800"; then
    run bash "$SCRIPT_DIR/submit_bridges_tesseract_pre1800.sh"
  fi
fi

echo "[remediate] re-checking..."
bash "$SCRIPT_DIR/bridges_training_automation_check.sh" || true
