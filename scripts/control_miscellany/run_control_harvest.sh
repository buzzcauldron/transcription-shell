#!/usr/bin/env bash
# Acquire the non-computus control miscellany queue (e-codices IIIF).
# Does not touch the computus harvest root or HIST_SLUGS.
#
# Images: Akdeniz / Constantine (this script).
# HTR: Bridges V100s (r5, llm off) while the Akdeniz 4090 is on computus;
#      or scripts/control_miscellany/run_control_htr.sh if the 4090 is free.
#
#   bash scripts/control_miscellany/run_control_harvest.sh
#   LIMIT_ACQUIRE=3 bash scripts/control_miscellany/run_control_harvest.sh   # smoke
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PY="${PYTHON:-python3}"

if [[ -d /mnt/constantinople/seth/latin-ms-workspace ]]; then
  JOBS_ROOT=/mnt/constantinople/seth/latin-ms-workspace/jobs_control_noncomputus
  HARVEST_ROOT=/mnt/constantinople/seth/latin-ms-workspace/control_miscellany_harvest
else
  JOBS_ROOT="${JOBS_ROOT:-$HOME/latin-ms-workspace/jobs_control_noncomputus}"
  HARVEST_ROOT="${HARVEST_ROOT:-$ROOT/references/control-miscellany/web_harvest}"
fi
mkdir -p "$JOBS_ROOT" "$HARVEST_ROOT"/{logs,queues}

QUEUE="${QUEUE:-$ROOT/references/control-miscellany/web_harvest/queues/acquire_queue.jsonl}"
if [[ ! -f "$QUEUE" ]]; then
  echo "missing $QUEUE — run scripts/control_miscellany/select_cohort.py first" >&2
  exit 1
fi
cp -a "$QUEUE" "$HARVEST_ROOT/queues/acquire_queue.jsonl"

if [[ -d /mnt/constantinople/seth/Projects/strigil ]]; then
  STRIGIL_DIR=/mnt/constantinople/seth/Projects/strigil
elif [[ -d "$HOME/Projects/strigil" ]]; then
  STRIGIL_DIR="$HOME/Projects/strigil"
else
  STRIGIL_DIR="${STRIGIL_DIR:-$HOME/Projects/strigil}"
fi
if [[ -x "$HOME/.venv-strigil/bin/python" ]]; then
  PY_ACQ="$HOME/.venv-strigil/bin/python"
else
  PY_ACQ="$PY"
fi

acq_args=(
  --queue "$HARVEST_ROOT/queues/acquire_queue.jsonl"
  --jobs-root "$JOBS_ROOT"
  --strigil-dir "$STRIGIL_DIR"
  --python "$PY_ACQ"
  --global-concurrency "${ACQUIRE_GLOBAL_CONCURRENCY:-4}"
  --strigil-workers "${STRIGIL_WORKERS:-8}"
  --harvest-root "$HARVEST_ROOT"
)
if [[ "${LIMIT_ACQUIRE:-0}" != "0" ]]; then
  acq_args+=(--limit "$LIMIT_ACQUIRE")
fi

echo "[control-harvest] jobs=$JOBS_ROOT queue=$QUEUE"
"$PY_ACQ" "$ROOT/scripts/computus/run_acquire_queue.py" "${acq_args[@]}"
echo "[control-harvest] HTR: gm-htr-r5-best via Bridges (submit_bridges_control_htr.sh) or run_control_htr.sh"
echo "[control-harvest] do not merge these jobs into historical_genre_core HIST_SLUGS"
