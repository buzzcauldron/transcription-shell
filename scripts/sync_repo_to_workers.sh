#!/usr/bin/env bash
# Push transcription-shell scripts and stylometry assets to remote workers.
#
# Usage:
#   bash scripts/sync_repo_to_workers.sh
#   bash scripts/sync_repo_to_workers.sh --akdeniz-only
#   bash scripts/sync_repo_to_workers.sh --bridges-only
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
AKDENIZ_HOST="${AKDENIZ_HOST:-akdeniz}"
AKDENIZ_REPO="/home/seth/Projects/transcription-shell"
STYLO_REPO="${STYLO_REPO:-$HOME/Projects/stylometry-r}"
BRIDGES_DTN="${BRIDGES_DTN:-bridges2-dtn}"
BRIDGES_REPO="/ocean/projects/hum260002p/sstrickland/transcriber-shell"

AKDENIZ=1
BRIDGES=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --akdeniz-only) BRIDGES=0; shift ;;
    --bridges-only) AKDENIZ=0; shift ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

sync_akdeniz() {
  echo "[sync] transcription-shell -> $AKDENIZ_HOST:$AKDENIZ_REPO"
  ssh -o BatchMode=yes "$AKDENIZ_HOST" "mkdir -p '$AKDENIZ_REPO'"
  rsync -az --delete \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '.venv-lineation/' \
    --exclude 'artifacts/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude 'vendor/historical-ocr/' \
    "$REPO/" "${AKDENIZ_HOST}:${AKDENIZ_REPO}/"

  if [[ -d "$STYLO_REPO/output/de_luce_r_rescore/reference_set_medieval_mixed" ]]; then
    echo "[sync] stylometry reference set -> $AKDENIZ_HOST"
    ssh -o BatchMode=yes "$AKDENIZ_HOST" \
      "mkdir -p /home/seth/Projects/stylometry-r/output/de_luce_r_rescore /home/seth/Projects/stylometry-r/scripts"
    rsync -az \
      "$STYLO_REPO/output/de_luce_r_rescore/reference_set_medieval_mixed/" \
      "${AKDENIZ_HOST}:/home/seth/Projects/stylometry-r/output/de_luce_r_rescore/reference_set_medieval_mixed/"
    rsync -az \
      "$STYLO_REPO/scripts/run_stylo_target.R" \
      "${AKDENIZ_HOST}:/home/seth/Projects/stylometry-r/scripts/"
  fi
}

sync_bridges() {
  echo "[sync] scripts -> $BRIDGES_DTN"
  bash "$REPO/scripts/sync_scripts_to_bridges.sh"
}

[[ "$AKDENIZ" -eq 1 ]] && sync_akdeniz
[[ "$BRIDGES" -eq 1 ]] && sync_bridges
echo "[sync] done"
