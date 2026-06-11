#!/usr/bin/env bash
# Sync local scripts/ (+ blind-test plan) to Bridges2 DTN.
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
REMOTE="${BRIDGES_DTN:-bridges2-dtn}:/ocean/projects/hum260002p/sstrickland/transcriber-shell/src"

rsync -avz -e "ssh -o BatchMode=yes" \
  "$REPO/scripts/" "${REMOTE}/scripts/"

if [[ -f "$REPO/artifacts/blind-test-training/plan.json" ]]; then
  ssh -o BatchMode=yes "${REMOTE%%:*}" "mkdir -p ${REMOTE#*:}/artifacts/blind-test-training"
  rsync -avz -e "ssh -o BatchMode=yes" \
    "$REPO/artifacts/blind-test-training/" \
    "${REMOTE}/artifacts/blind-test-training/"
fi

echo "[sync] scripts -> Bridges done"
