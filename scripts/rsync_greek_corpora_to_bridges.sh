#!/usr/bin/env bash
# Stage local Greek HTR corpora (+ optional PTA seed) to Bridges2 DTN.
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCAL_GREEK="${LOCAL_GREEK:-$HOME/src/htr-corpora-greek}"
REMOTE_ROOT="${BRIDGES_DTN:-bridges2-dtn}:/ocean/projects/hum260002p/sstrickland/transcriber-shell/src"
SEED_LOCAL="${SEED_LOCAL:-$HOME/src/greek_minuscule_s9-12_NFC.mlmodel}"

if [[ ! -d "$LOCAL_GREEK" ]]; then
  echo "Missing $LOCAL_GREEK — run scripts/download_greek_htr_corpora.sh first" >&2
  exit 1
fi

echo "[rsync-greek] $LOCAL_GREEK -> ${REMOTE_ROOT}/htr-corpora-greek/"
rsync -avh --partial --info=progress2 -e "ssh -o BatchMode=yes" \
  "$LOCAL_GREEK/" "${REMOTE_ROOT}/htr-corpora-greek/"

if [[ -f "$SEED_LOCAL" ]]; then
  echo "[rsync-greek] seed $SEED_LOCAL"
  rsync -avh -e "ssh -o BatchMode=yes" \
    "$SEED_LOCAL" "${REMOTE_ROOT}/greek_minuscule_s9-12_NFC.mlmodel"
else
  echo "[rsync-greek] WARN: no seed at $SEED_LOCAL (Zenodo 15838142)"
fi

bash "$REPO/scripts/sync_scripts_to_bridges.sh"
echo "[rsync-greek] done"
