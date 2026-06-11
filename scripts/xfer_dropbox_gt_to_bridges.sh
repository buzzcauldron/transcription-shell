#!/usr/bin/env bash
# Rsync human GT manuscripts from Dropbox (Mac) to Bridges2.
# Run on the Mac where Dropbox is linked (halxiii). Cloud-only files download as rsync reads them.
#
# Usage:
#   bash scripts/xfer_dropbox_gt_to_bridges.sh
#   bash scripts/xfer_dropbox_gt_to_bridges.sh --dry-run
#
# Environment:
#   DROPBOX_ROOT   default: ~/Library/CloudStorage/Dropbox
#   BRIDGES_GT     default: /ocean/projects/hum260002p/sstrickland/transcriber-shell/gt-mss/dropbox
#   BRIDGES_HOST   default: bridges2-dtn (see ~/.ssh/config)

set -euo pipefail

DROPBOX_ROOT="${DROPBOX_ROOT:-$HOME/Library/CloudStorage/Dropbox}"
BRIDGES_GT="${BRIDGES_GT:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/gt-mss/dropbox}"
BRIDGES_HOST="${BRIDGES_HOST:-bridges2-dtn}"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

ensure_remote_dir() {
  local remote_dir="$1"
  echo "[dropbox-gt] ensuring remote dir: ${BRIDGES_HOST}:${remote_dir}"
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  ssh -o StrictHostKeyChecking=accept-new "$BRIDGES_HOST" "mkdir -p '${remote_dir}'"
}

xfer() {
  local src="$1" dest_sub="$2"
  local -a rsync_cmd=(
    rsync -avh --partial --append-verify --info=progress2
    --exclude='.git/'
    --exclude='.Trash/'
    --exclude='*.xml~'
    --exclude='*Conflict*'
    --exclude='.DS_Store'
    -e "ssh -o StrictHostKeyChecking=accept-new"
  )
  if [[ ! -e "$src" ]]; then
    echo "[skip] missing: $src"
    return 0
  fi
  local remote="${BRIDGES_GT}/${dest_sub}"
  echo "[xfer] $src -> ${BRIDGES_HOST}:${remote}/"
  ensure_remote_dir "$remote"
  if [[ "$DRY_RUN" == "1" ]]; then
    "${rsync_cmd[@]}" -n "$src/" "${BRIDGES_HOST}:${BRIDGES_GT}/${dest_sub}/"
  else
    "${rsync_cmd[@]}" "$src/" "${BRIDGES_HOST}:${BRIDGES_GT}/${dest_sub}/"
  fi
}

echo "[dropbox-gt] $(date -Iseconds) Dropbox GT -> Bridges"
echo "  dropbox: $DROPBOX_ROOT"
echo "  dest:    $BRIDGES_GT"

ensure_remote_dir "$BRIDGES_GT"

# Core human GT trees referenced by transcription-shell / latin_ms pipeline
xfer "$DROPBOX_ROOT/Transcriptions/Done lines" "Transcriptions/Done-lines"
xfer "$DROPBOX_ROOT/Transcriptions/Deeds material" "Transcriptions/Deeds-material"
xfer "$DROPBOX_ROOT/Transcriptions/Coroners' Rolls" "Transcriptions/Coroners-Rolls"
xfer "$DROPBOX_ROOT/Transcriptions/Semi-diplomatic transcriptions and images" "Transcriptions/Semi-diplomatic"
xfer "$DROPBOX_ROOT/Transcriptions/Non-diplomatic transcriptions and images" "Transcriptions/Non-diplomatic"
xfer "$DROPBOX_ROOT/Transcriptions/Newly added non-diplomatic" "Transcriptions/Newly-added-non-diplomatic"
xfer "$DROPBOX_ROOT/Transcriptions/Validation set" "Transcriptions/Validation-set"
xfer "$DROPBOX_ROOT/Transcriptions/Untranscribed cases" "Transcriptions/Untranscribed-cases"
xfer "$DROPBOX_ROOT/Seth/Mac/Documents/manuscript-data" "manuscript-data"
xfer "$DROPBOX_ROOT/Seth/Cornell/Spring 2018/Vatican Film Library Fellowship Summer 2018/Bibliotheque Municipale De Tours 746" "Cornell/Tours-746"

echo "[dropbox-gt] $(date -Iseconds) done"
