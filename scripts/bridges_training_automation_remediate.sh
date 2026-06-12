#!/usr/bin/env bash
# Remediate common Bridges training failures (idempotent). For automation use.
#
#   bash scripts/bridges_training_automation_remediate.sh
#   bash scripts/bridges_training_automation_remediate.sh --dry-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SHELL_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_REMOTE="/ocean/projects/hum260002p/sstrickland/transcriber-shell/src"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

# shellcheck disable=SC1091
source "$SCRIPT_DIR/bridges_ssh.sh"

run() {
  if [[ "$DRY" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    echo "[remediate] $*"
    "$@"
  fi
}

echo "[remediate] running health check first..."
bash "$SCRIPT_DIR/bridges_training_automation_check.sh" && CHECK_OK=1 || CHECK_OK=0
[[ "${CHECK_OK:-0}" -eq 1 ]] && { echo "[remediate] already healthy"; exit 0; }

echo "[remediate] cancelling DependencyNeverSatisfied orphans"
bridges_ssh "squeue -u \$USER -h -o '%i %r' | awk '\$2 == \"(DependencyNeverSatisfied)\" { print \$1 }'" \
  | while read -r jid; do
    [[ -z "$jid" ]] && continue
    run bridges_ssh "scancel $jid" || true
  done

# Sync scripts + fix venvs before resubmit (fast path first)
run bash "$SCRIPT_DIR/sync_scripts_to_bridges.sh"

run bridges_ssh "bash $SRC_REMOTE/scripts/bridges_fix_kraken_numpy.sh" || true
run bridges_ssh "bash $SRC_REMOTE/scripts/fix_bridges_venv_paths.sh" || true

# historical-ocr sync only when tess-pre1800 needs it (can be slow)
if ! bridges_ssh "test -f $SRC_REMOTE/models/lat_pre1800.traineddata"; then
  HIST_REPO="${HISTORICAL_OCR_ROOT:-$SHELL_REPO/../historical-ocr}"
  if [[ -d "$HIST_REPO" ]] && ! bridges_ssh "test -x /ocean/projects/hum260002p/sstrickland/historical-ocr/.venv/bin/historical-ocr"; then
    run bash "$SCRIPT_DIR/sync_historical_ocr.sh" || true
  fi
fi

# Smart HTR resubmit (resume / downstream-only / full chain)
run bridges_ssh "bash $SRC_REMOTE/scripts/bridges_resubmit_htr.sh${DRY:+ --dry-run}"

# Resubmit tess-pre1800 if not running and no model yet
if ! bridges_ssh "test -f $SRC_REMOTE/models/lat_pre1800.traineddata"; then
  if ! bridges_ssh "squeue -u \$USER -h -o '%j' | grep -q tess-pre1800"; then
    run bash "$SCRIPT_DIR/submit_bridges_tesseract_pre1800.sh"
  fi
fi

echo "[remediate] re-checking..."
if bash "$SCRIPT_DIR/bridges_training_automation_check.sh"; then
  echo "[remediate] healthy"
  exit 0
fi
echo "[remediate] issues remain — see report above"
exit 1
