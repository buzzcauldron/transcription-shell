#!/usr/bin/env bash
# Resume or start latin_lineation_mvp training after reboot (or any time).
#
# Usage:
#   export LATIN_DOCUMENTS_DATA=/path/to/latin_documents/data
#   export LINE_MASK_OUT=/path/to/line_mask_unet.pt   # optional
#   ./scripts/resume-lineation-training.sh
#
# If LINE_MASK_OUT.train.pt exists next to LINE_MASK_OUT, training continues from the last
# completed epoch (--resume auto). Otherwise starts from epoch 1.
#
# Optional: run at boot with systemd (user unit) — see examples/latin_lineation_mvp/README.md

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="${LATIN_DOCUMENTS_DATA:-}"
OUT="${LINE_MASK_OUT:-$ROOT/artifacts/training/line_mask_unet.pt}"
EPOCHS="${LINE_MASK_EPOCHS:-100}"
DEVICE="${LINE_MASK_DEVICE:-cuda:0}"

if [[ -z "$DATA" ]]; then
  echo "Set LATIN_DOCUMENTS_DATA to your latin_documents/data directory." >&2
  exit 1
fi
if [[ ! -d "$DATA" ]]; then
  echo "Not a directory: $DATA" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"
cd "$ROOT"
if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

exec latin-lineation-train \
  --data-dir "$DATA" \
  --epochs "$EPOCHS" \
  --device "$DEVICE" \
  --out "$OUT" \
  --resume auto
