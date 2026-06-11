#!/usr/bin/env bash
# Clean anaconda 3.12 for corpus prep — no kraken venv on PYTHONPATH.
# Source from bridges_latin_corpus_prep.sh or bridges_start.sh preflight.
export PYTHONNOUSERSITE=1
unset PYTHONPATH
unset VIRTUAL_ENV

module load anaconda3 2>/dev/null || true
export BRIDGES_PYTHON="${BRIDGES_PYTHON:-/opt/packages/anaconda3-2024.10-1/bin/python3.12}"
export PY_RUN="$BRIDGES_PYTHON"

_preflight() {
  "$PY_RUN" -c "import traceback, yaml, concurrent.futures" 2>/dev/null
}

if ! _preflight; then
  echo "[prep-env] retrying preflight after brief pause..." >&2
  sleep 3
  if ! _preflight; then
    echo "[prep-env] FATAL: clean python preflight failed: $PY_RUN" >&2
    "$PY_RUN" -c "import traceback, yaml, concurrent.futures" 2>&1 || true
    return 1 2>/dev/null || exit 1
  fi
fi
