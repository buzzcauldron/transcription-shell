#!/usr/bin/env bash
# Rsync working kraken venv from akdeniz to Bridges (run on akdeniz).
set -euo pipefail

SRC_VENV="${SRC_VENV:-$HOME/src/.venv}"
BRIDGES_DTN="${BRIDGES_DTN:-bridges2-dtn}"
PROJECT="${PROJECT:-/ocean/projects/hum260002p/sstrickland/transcriber-shell}"
DEST="$PROJECT/kraken-venv"

[[ -x "$SRC_VENV/bin/ketos" ]] || { echo "no venv at $SRC_VENV"; exit 1; }

echo "[venv-rsync] $SRC_VENV -> $BRIDGES_DTN:$DEST (~8GB)"
rsync -avh --partial --info=progress2 \
  -e "ssh -o StrictHostKeyChecking=accept-new" \
  "$SRC_VENV/" "$BRIDGES_DTN:$DEST/"

echo "[venv-rsync] done — run fix_bridges_venv_paths.sh on Bridges login"
