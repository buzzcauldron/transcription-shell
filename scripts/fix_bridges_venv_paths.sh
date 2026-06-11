#!/usr/bin/env bash
# Fix absolute paths after rsyncing a venv from akdeniz to Bridges.
set -euo pipefail

VENV="${VENV:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/kraken-venv}"
OLD_PATHS=(
  /home/seth/src/.venv
  /home/seth/.venv-kraken
)

[[ -d "$VENV/bin" ]] || { echo "missing venv: $VENV"; exit 1; }

for old in "${OLD_PATHS[@]}"; do
  while IFS= read -r -d '' f; do
    sed -i "s|${old}|${VENV}|g" "$f"
  done < <(grep -rl "${old}" "$VENV" 2>/dev/null | tr '\n' '\0' || true)
done

export PYTHONNOUSERSITE=True
module load python 2>/dev/null || true
"$VENV/bin/python" -c "import torch, kraken; print('ok', torch.__version__)"
"$VENV/bin/ketos" --help | head -2
