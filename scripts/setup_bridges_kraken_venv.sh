#!/usr/bin/env bash
# Create kraken 7.0.2 venv on Bridges2 under /ocean (run on login node).
#
#   cd /ocean/projects/hum260002p/sstrickland/transcriber-shell/src
#   bash scripts/setup_bridges_kraken_venv.sh
#
# GPU nodes have CUDA; login nodes do not — that is normal. Training runs via sbatch.

set -euo pipefail

PROJECT="${PROJECT:-/ocean/projects/hum260002p/sstrickland/transcriber-shell}"
VENV="${VENV:-$PROJECT/kraken-venv}"

export PYTHONNOUSERSITE=True
module load python 2>/dev/null || module load anaconda3 2>/dev/null || true

if ! command -v python3 >/dev/null; then
  echo "ERROR: load python first: module load python" >&2
  exit 1
fi

echo "[venv] python: $(which python3) ($(python3 --version))"
echo "[venv] target:   $VENV"

if [[ -d "$VENV" ]] && ! "$VENV/bin/python" -c "import sys" 2>/dev/null; then
  echo "[venv] removing broken venv"
  rm -rf "$VENV"
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

python -m pip install -U pip setuptools wheel
# V100 on Bridges: CUDA 11.8 wheels are the safe default
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
python -m pip install 'kraken==7.0.2'

echo "[venv] smoke test (CPU login node — CUDA False is OK here)"
python -c "import torch; import kraken; print('torch', torch.__version__, 'cuda_available', torch.cuda.is_available())"
"$VENV/bin/ketos" --help | head -3

echo "[venv] ready: source $VENV/bin/activate"
