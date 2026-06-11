#!/usr/bin/env bash
# Activate relocated akdeniz kraken venv on Bridges (anaconda 3.12 + site-packages).
# Usage: source scripts/bridges_kraken_activate.sh
VENV="${VENV:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/kraken-venv}"

export PYTHONNOUSERSITE=True
module load anaconda3 2>/dev/null || true

PY="${BRIDGES_PYTHON:-/opt/packages/anaconda3-2024.10-1/bin/python3}"
export BRIDGES_PYTHON="$PY"
export VIRTUAL_ENV="$VENV"
export PYTHONPATH="${VENV}/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export PATH="${VENV}/bin:${PATH}"

# ketos console script from akdeniz points at /home/seth — rewrite once per activate
if [[ ! -x "${VENV}/bin/ketos" ]] || ! head -1 "${VENV}/bin/ketos" | grep -q anaconda3; then
  cat > "${VENV}/bin/ketos" <<EOF
#!${PY}
import sys
sys.path.insert(0, "${VENV}/lib/python3.12/site-packages")
from kraken.ketos import cli
if __name__ == "__main__":
    sys.argv[0] = sys.argv[0].removesuffix(".exe")
    sys.exit(cli())
EOF
  chmod +x "${VENV}/bin/ketos"
fi

python() { "$PY" "$@"; }
python3() { "$PY" "$@"; }
export -f python python3
