#!/usr/bin/env bash
# Make rsynced kraken venv compatible with Bridges anaconda (matplotlib + torch).
# - Drops venv numpy 2.x so anaconda numpy 1.x is used (matplotlib ABI match).
# - Purges stale .pyc from akdeniz rsync.
set -euo pipefail

VENV="${VENV:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/kraken-venv}"
ANACONDA_ROOT="${ANACONDA_ROOT:-/opt/packages/anaconda3-2024.10-1}"
PY="${BRIDGES_PYTHON:-${ANACONDA_ROOT}/bin/python3.12}"
SP="$VENV/lib/python3.12/site-packages"

[[ -d "$SP" ]] || { echo "[numpy-fix] missing $SP"; exit 1; }

echo "[numpy-fix] purge stale .pyc"
find "$VENV" -name '*.pyc' -delete 2>/dev/null || true
find "$VENV" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

echo "[numpy-fix] remove venv numpy (use anaconda numpy for matplotlib)"
rm -rf "$SP/numpy" "$SP"/numpy-*.dist-info 2>/dev/null || true

export PYTHONNOUSERSITE=1
module load anaconda3 2>/dev/null || true
export LD_LIBRARY_PATH="${ANACONDA_ROOT}/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$SP"

"$PY" -c "import numpy, matplotlib, torch, kraken; print('ok', numpy.__version__, matplotlib.__version__, torch.__version__)"
