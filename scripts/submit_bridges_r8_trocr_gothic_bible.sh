#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGIN="${BRIDGES_LOGIN:-bridges2}"
bash "$SCRIPT_DIR/sync_scripts_to_bridges.sh"
JOB=$(ssh -o BatchMode=yes "$LOGIN" \
  "cd /ocean/projects/hum260002p/sstrickland/transcriber-shell/src && sbatch --parsable scripts/r8_trocr_gothic_bible.sbatch")
echo "[bridges] trocr-r8-gothic job $JOB"
