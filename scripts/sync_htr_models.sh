#!/usr/bin/env bash
# Sync Kraken HTR best weights across local Mac, akdeniz, and Bridges2.
#
# Usage:
#   bash scripts/sync_htr_models.sh pull              # Bridges -> local
#   bash scripts/sync_htr_models.sh push-akdeniz      # local -> akdeniz
#   bash scripts/sync_htr_models.sh push-bridges      # local -> Bridges (fill gaps)
#   bash scripts/sync_htr_models.sh sync-all          # pull, push-bridges, push-akdeniz
#
# Environment:
#   AKDENIZ_HOST   default: akdeniz
#   BRIDGES_HOST   default: bridges2-dtn
#   HTR_LOCAL_DIR  default: ~/src/latin_documents
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL="${HTR_LOCAL_DIR:-${HOME}/src/latin_documents}"
AKDENIZ_HOST="${AKDENIZ_HOST:-akdeniz}"
AKDENIZ_DESTS=(
  "/home/seth/src/latin_documents"
  "/home/seth/src"
  "/mnt/constantinople/seth/src/latin_documents"
  "/mnt/constantinople/seth/src"
)
BRIDGES_HOST="${BRIDGES_HOST:-bridges2-dtn}"
BRIDGES_DIR="${BRIDGES_HTR_DIR:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"

MODELS=(
  gm-htr-r2.mlmodel_best.mlmodel
  gm-htr-r5-best.mlmodel
  gm-htr-computus_best.mlmodel
  gm-htr-anglicana_best.mlmodel
  gm-htr-psalter_best.mlmodel
  gm-htr-r6-core_best.mlmodel
  gm-htr-r7-full_best.mlmodel
  gm-htr-r8-gothic-bible_best.mlmodel
  gm-htr-greek-minuscule_best.mlmodel
  gm-seg.mlmodel
)

pull_from_bridges() {
  bash "$SRC/scripts/pull_bridges_htr_models.sh"
}

push_to_akdeniz() {
  mkdir -p "$LOCAL"
  for dest in "${AKDENIZ_DESTS[@]}"; do
    ssh -o BatchMode=yes "$AKDENIZ_HOST" "mkdir -p '$dest'"
  done
  for m in "${MODELS[@]}"; do
    [[ -f "$LOCAL/$m" ]] || continue
    for dest in "${AKDENIZ_DESTS[@]}"; do
      rsync -avz -e "ssh -o BatchMode=yes" \
        "$LOCAL/$m" "${AKDENIZ_HOST}:${dest}/"
    done
  done
  echo "[sync-htr] akdeniz latin_documents:"
  ssh -o BatchMode=yes "$AKDENIZ_HOST" \
    "ls -lah ${AKDENIZ_DESTS[0]}/gm-htr*.mlmodel* ${AKDENIZ_DESTS[0]}/gm-seg.mlmodel || true"
}

push_to_bridges() {
  mkdir -p "$LOCAL"
  ssh -o BatchMode=yes "$BRIDGES_HOST" "mkdir -p '$BRIDGES_DIR'"
  for m in "${MODELS[@]}"; do
    [[ -f "$LOCAL/$m" ]] || continue
    # Only upload if missing or local is newer (rsync -u)
    rsync -avzu -e "ssh -o BatchMode=yes" \
      "$LOCAL/$m" "${BRIDGES_HOST}:${BRIDGES_DIR}/"
  done
  echo "[sync-htr] bridges models:"
  # bridges2-dtn is a restricted rsync/scp shell — no redirects or `||`.
  ssh -o BatchMode=yes "$BRIDGES_HOST" \
    ls -lah "${BRIDGES_DIR}/gm-htr-r7-full_best.mlmodel" "${BRIDGES_DIR}/gm-seg.mlmodel"
}

cmd="${1:-sync-all}"
case "$cmd" in
  pull) pull_from_bridges ;;
  push-akdeniz) push_to_akdeniz ;;
  push-bridges) push_to_bridges ;;
  sync-all)
    pull_from_bridges
    push_to_bridges
    push_to_akdeniz
    ;;
  *)
    echo "Usage: $0 {pull|push-akdeniz|push-bridges|sync-all}" >&2
    exit 1
    ;;
esac
