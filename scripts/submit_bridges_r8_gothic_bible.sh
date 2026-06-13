#!/usr/bin/env bash
# Submit r8 Gothic Bible HTR fine-tune on Bridges2.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGIN="${BRIDGES_LOGIN:-bridges2}"

bash "$SCRIPT_DIR/sync_scripts_to_bridges.sh"

JOB=$(ssh -o BatchMode=yes "$LOGIN" \
  "cd /ocean/projects/hum260002p/sstrickland/transcriber-shell/src && sbatch --parsable scripts/r8_gothic_bible_retrain.sbatch")

echo "[bridges] r8-gothic-bible job $JOB"
echo "  ssh $LOGIN tail -f /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/htr-r8-gothic-${JOB}.out"
