#!/usr/bin/env bash
# Sync Greek corpora + scripts to Bridges2 and submit minuscule HTR fine-tune.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGIN="${BRIDGES_LOGIN:-bridges2}"
SYNC="${SYNC_GREEK:-1}"

if [[ "$SYNC" == "1" ]]; then
  bash "$SCRIPT_DIR/rsync_greek_corpora_to_bridges.sh"
else
  bash "$SCRIPT_DIR/sync_scripts_to_bridges.sh"
fi

JOB=$(ssh -o BatchMode=yes "$LOGIN" \
  "cd /ocean/projects/hum260002p/sstrickland/transcriber-shell/src && sbatch --parsable scripts/r_greek_minuscule_retrain.sbatch")

echo "[bridges] greek-minuscule job $JOB"
echo "  ssh $LOGIN squeue -u \$USER"
echo "  ssh $LOGIN tail -f /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/htr-greek-min-${JOB}.out"
