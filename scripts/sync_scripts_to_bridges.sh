#!/usr/bin/env bash
# Sync local scripts/ (+ blind-test plan) to Bridges2 DTN.
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/bridges_ssh.sh"
REMOTE="${BRIDGES_DTN}:/ocean/projects/hum260002p/sstrickland/transcriber-shell/src"
RSYNC_SSH="$(bridges_rsync_ssh_e)"

rsync -avz -e "$RSYNC_SSH" \
  "$REPO/scripts/" "${REMOTE}/scripts/"

if [[ -f "$REPO/artifacts/blind-test-training/plan.json" ]]; then
  bridges_ssh "${REMOTE%%:*}" "mkdir -p ${REMOTE#*:}/artifacts/blind-test-training"
  rsync -avz -e "$RSYNC_SSH" \
    "$REPO/artifacts/blind-test-training/" \
    "${REMOTE}/artifacts/blind-test-training/"
fi

echo "[sync] scripts -> Bridges done"
