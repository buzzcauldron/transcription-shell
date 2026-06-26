#!/usr/bin/env bash
# Cancel stale htr-* jobs and submit fresh r6 + r8 resume chunks.
#
#   bash scripts/bridges_restart_htr.sh
#   bash scripts/bridges_restart_htr.sh --status
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGIN="${BRIDGES_LOGIN:-bridges2}"

bash "$SCRIPT_DIR/sync_scripts_to_bridges.sh"

ssh -o BatchMode=yes "$LOGIN" bash -s -- "${1:-}" <<'REMOTE'
set -euo pipefail
SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
SCRIPTS="$SRC/scripts"
STATUS="${1:-}"

log() { echo "[restart-htr] $(date '+%H:%M:%S') $*"; }

if [[ "$STATUS" == "--status" ]]; then
  squeue -u "$USER" -o "%.10i %.18j %.8T %.12M %E" | grep -E 'JOBID|htr-r6|htr-r7|htr-r8|trocr-r8' || true
  ls -lt "$SRC/gm-htr-r6-core"/checkpoint_*.ckpt 2>/dev/null | head -1 || true
  ls -lt "$SRC/gm-htr-r8-gothic-bible"/checkpoint_*.ckpt 2>/dev/null | head -1 || true
  exit 0
fi

while IFS= read -r line; do
  jid=$(echo "$line" | awk '{print $1}')
  jname=$(echo "$line" | awk '{print $2}')
  log "scancel $jname ($jid)"
  scancel "$jid" || true
done < <(squeue -u "$USER" -h -o "%i %j" 2>/dev/null | awk '$2 ~ /^htr-/ || $2 ~ /^trocr-r8/')

[[ -d "$SRC/gm-htr-r6-core" ]] || { echo "ERROR: missing r6 checkpoint dir" >&2; exit 1; }
[[ -d "$SRC/gm-htr-r8-gothic-bible" ]] || { echo "ERROR: missing r8 checkpoint dir" >&2; exit 1; }

cd "$SRC"
R6=$(sbatch --parsable -A hum260002p "$SCRIPTS/r6_core_resume.sbatch")
R8=$(sbatch --parsable -A hum260002p "$SCRIPTS/r8_gothic_bible_resume.sbatch")
log "submitted r6 resume $R6 (from $(basename "$(ls -t "$SRC/gm-htr-r6-core"/checkpoint_*.ckpt | grep -v abort | head -1)"))"
log "submitted r8 resume $R8 (from $(basename "$(ls -t "$SRC/gm-htr-r8-gothic-bible"/checkpoint_*.ckpt | grep -v abort | head -1)"))"
log "r7 / trocr-r8 auto-queue on early-stop"
echo ""
squeue -u "$USER" -o "%.10i %.18j %.8T %.12M %E" | grep -E 'JOBID|htr-r6|htr-r7|htr-r8|trocr-r8' || true
REMOTE
