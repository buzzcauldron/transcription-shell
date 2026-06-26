#!/usr/bin/env bash
# Resume r8 Gothic Bible Kraken fine-tune (48h chunks) + auto trocr when early-stop.
#
#   bash scripts/bridges_resume_r8.sh
#   bash scripts/bridges_resume_r8.sh --status
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGIN="${BRIDGES_LOGIN:-bridges2}"
SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src

bash "$SCRIPT_DIR/sync_scripts_to_bridges.sh"

ssh -o BatchMode=yes "$LOGIN" bash -s -- "${1:-}" <<'REMOTE'
set -euo pipefail
SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
SCRIPTS="$SRC/scripts"
STATUS="${1:-}"

log() { echo "[resume-r8] $(date '+%H:%M:%S') $*"; }

if [[ "$STATUS" == "--status" ]]; then
  squeue -u "$USER" -o "%.10i %.16j %.8T %.12M %E" | grep -E 'JOBID|htr-r8|trocr-r8' || true
  ls -lt "$SRC/gm-htr-r8-gothic-bible"/checkpoint_*.ckpt 2>/dev/null | head -3 || true
  ls -la "$SRC/gm-htr-r8-gothic-bible_best.mlmodel" 2>/dev/null || echo "  (no r8 best mlmodel yet)"
  exit 0
fi

while IFS= read -r jid; do
  [[ -n "$jid" ]] || continue
  log "scancel orphan $jid"
  scancel "$jid" || true
done < <(squeue -u "$USER" -h -o "%i %j %r" | awk '$3 ~ /DependencyNeverSatisfied/ && ($2 ~ /r8-gothic|trocr-r8/) {print $1}')

if squeue -u "$USER" -h -o "%j %T" | awk '$1=="htr-r8-gothic-r" && ($2=="RUNNING" || $2=="PENDING") {found=1} END{exit !found}'; then
  log "htr-r8-gothic-r already queued/running"
  squeue -u "$USER" -o "%.10i %.16j %.8T %E" | grep -E 'JOBID|htr-r8|trocr-r8' || true
  exit 0
fi

OUT="$SRC/gm-htr-r8-gothic-bible"
CKPT=$(ls -t "$OUT"/checkpoint_*.ckpt 2>/dev/null | grep -v abort | head -1 || true)
[[ -n "$CKPT" ]] || { echo "ERROR: no r8 checkpoint in $OUT" >&2; exit 1; }

log "latest ckpt: $(basename "$CKPT")"
cd "$SRC"
R8=$(sbatch --parsable -A hum260002p "$SCRIPTS/r8_gothic_bible_resume.sbatch")
log "submitted htr-r8-gothic-r job $R8"
log "trocr-r8-gothic auto-submits when early-stop exports best mlmodel"
echo ""
squeue -u "$USER" -o "%.10i %.16j %.8T %.12M %E" | grep -E 'JOBID|htr-r6|htr-r8|trocr-r8' || true
REMOTE
