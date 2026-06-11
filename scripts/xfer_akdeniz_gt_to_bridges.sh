#!/usr/bin/env bash
# Rsync akdeniz kraken GT manuscript dirs to Bridges2 (run on akdeniz).
#
# Usage:
#   bash ~/src/scripts/xfer_akdeniz_gt_to_bridges.sh
#   bash ~/src/scripts/xfer_akdeniz_gt_to_bridges.sh --dry-run

set -euo pipefail

BRIDGES_GT="${BRIDGES_GT:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/gt-mss/akdeniz}"
BRIDGES_HOST="${BRIDGES_HOST:-bridges2-dtn}"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

ensure_remote_base() {
  echo "[akdeniz-gt] ensuring remote base: ${BRIDGES_HOST}:${BRIDGES_GT}"
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  ssh -o StrictHostKeyChecking=accept-new "$BRIDGES_HOST" "mkdir -p '${BRIDGES_GT}'"
}

xfer_dir() {
  local src="$1" name="$2"
  local -a rsync_cmd=(
    rsync -avh --partial --append-verify --info=progress2
    --exclude='.git/'
    -e "ssh -o StrictHostKeyChecking=accept-new"
  )
  [[ -d "$src" ]] || { echo "[skip] $src"; return 0; }
  echo "[xfer] $src (~$(du -sh "$src" | awk '{print $1}')) -> ${BRIDGES_GT}/${name}/"
  if [[ "$DRY_RUN" == "1" ]]; then
    "${rsync_cmd[@]}" -n "$src/" "${BRIDGES_HOST}:${BRIDGES_GT}/${name}/"
  else
    "${rsync_cmd[@]}" "$src/" "${BRIDGES_HOST}:${BRIDGES_GT}/${name}/"
  fi
}

echo "[akdeniz-gt] $(date -Iseconds) -> $BRIDGES_GT"

ensure_remote_base

xfer_dir "$HOME/kraken-vatlib-gt"     kraken-vatlib-gt
xfer_dir "$HOME/kraken-cp40-gt"       kraken-cp40-gt
xfer_dir "$HOME/kraken-done-lines-gt" kraken-done-lines-gt
xfer_dir "$HOME/deed-finetune-gt"     deed-finetune-gt
xfer_dir "$HOME/src/deed-finetune-gt" deed-finetune-gt-src
xfer_dir "$HOME/src/kraken-vatlib-gt" kraken-vatlib-gt-src

echo "[akdeniz-gt] done"
