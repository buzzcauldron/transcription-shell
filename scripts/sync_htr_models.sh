#!/usr/bin/env bash
# Sync Kraken HTR best weights across local Mac, akdeniz, and Bridges2.
#
# Usage:
#   bash scripts/sync_htr_models.sh pull              # Bridges -> local
#   bash scripts/sync_htr_models.sh push-akdeniz      # local -> akdeniz
#   bash scripts/sync_htr_models.sh sync-all          # pull then push-akdeniz
#
# Environment:
#   AKDENIZ_HOST   default: akdeniz
#   BRIDGES_DTN    default: bridges2-dtn
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL="${HOME}/src/latin_documents"
AKDENIZ_HOST="${AKDENIZ_HOST:-akdeniz}"
AKDENIZ_DEST="/home/seth/src/latin_documents"
BRIDGES_REMOTE="${BRIDGES_DTN:-bridges2-dtn}:/ocean/projects/hum260002p/sstrickland/transcriber-shell/src"

MODELS=(
  gm-htr-r2.mlmodel_best.mlmodel
  gm-htr-r5-best.mlmodel
  gm-htr-computus_best.mlmodel
  gm-htr-r6-core_best.mlmodel
  gm-htr-r7-full_best.mlmodel
  gm-htr-r8-gothic-bible_best.mlmodel
)

pull_from_bridges() {
  bash "$SRC/scripts/pull_bridges_htr_models.sh"
}

push_to_akdeniz() {
  mkdir -p "$LOCAL"
  ssh -o BatchMode=yes "$AKDENIZ_HOST" "mkdir -p '$AKDENIZ_DEST'"
  for m in "${MODELS[@]}"; do
    if [[ -f "$LOCAL/$m" ]]; then
      rsync -avz --ignore-missing-args -e "ssh -o BatchMode=yes" \
        "$LOCAL/$m" "${AKDENIZ_HOST}:${AKDENIZ_DEST}/"
    fi
  done
  echo "[sync-htr] akdeniz models:"
  ssh -o BatchMode=yes "$AKDENIZ_HOST" "ls -lah '${AKDENIZ_DEST}'/gm-htr*.mlmodel* 2>/dev/null || true"
}

cmd="${1:-sync-all}"
case "$cmd" in
  pull) pull_from_bridges ;;
  push-akdeniz) push_to_akdeniz ;;
  sync-all)
    pull_from_bridges
    push_to_akdeniz
    ;;
  *)
    echo "Usage: $0 {pull|push-akdeniz|sync-all}" >&2
    exit 1
    ;;
esac
