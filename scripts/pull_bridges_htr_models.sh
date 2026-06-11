#!/usr/bin/env bash
# Pull latest GM HTR weights from Bridges2 DTN into ~/src/latin_documents/.
set -euo pipefail

REMOTE="bridges2-dtn:/ocean/projects/hum260002p/sstrickland/transcriber-shell/src"
DEST="${HOME}/src/latin_documents"
mkdir -p "$DEST"

MODELS=(
  gm-htr-r2.mlmodel_best.mlmodel
  gm-htr-r5-best.mlmodel
  gm-htr-anglicana_best.mlmodel
  gm-htr-psalter_best.mlmodel
  gm-htr-r6-core_best.mlmodel
  gm-htr-r7-full_best.mlmodel
)

for m in "${MODELS[@]}"; do
  if rsync -avz --ignore-missing-args -e "ssh -o BatchMode=yes" "${REMOTE}/${m}" "${DEST}/"; then
    :
  fi
done

echo "[pull] local models:"
ls -lah "${DEST}"/gm-htr*.mlmodel* 2>/dev/null || true
