#!/usr/bin/env bash
# Resume r6-core from latest checkpoint (48h GPU-shared chunks) and queue r7 when r6 early-stops.
#
# GPU-shared walltime is capped at 48h; r6_core_resume.sbatch self-chains with afterany until
# ketos early-stop exports gm-htr-r6-core_best.mlmodel, then submits r7-full.
#
# Usage (Mac or Bridges login):
#   bash scripts/bridges_resume_r6_r7.sh
#   bash scripts/bridges_resume_r6_r7.sh --status
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

log() { echo "[resume-r6] $(date '+%H:%M:%S') $*"; }

if [[ "$STATUS" == "--status" ]]; then
  squeue -u "$USER" -o "%.10i %.16j %.8T %.12M %E" | grep -E 'JOBID|htr-r6|htr-r7' || true
  ls -lt "$SRC/gm-htr-r6-core"/checkpoint_*.ckpt 2>/dev/null | head -3 || true
  ls -la "$SRC/gm-htr-r6-core_best.mlmodel" 2>/dev/null || echo "  (no r6 best mlmodel yet)"
  exit 0
fi

# Drop orphaned dependents (failed parent → DependencyNeverSatisfied).
while IFS= read -r jid; do
  [[ -n "$jid" ]] || continue
  log "scancel orphan $jid"
  scancel "$jid" || true
done < <(squeue -u "$USER" -h -o "%i %r" | awk '$2 ~ /DependencyNeverSatisfied/ {print $1}')

if squeue -u "$USER" -h -o "%j %T" | awk '$1=="htr-r6-core-r" && ($2=="RUNNING" || $2=="PENDING") {found=1} END{exit !found}'; then
  log "htr-r6-core-r already queued/running — nothing to submit"
  squeue -u "$USER" -o "%.10i %.16j %.8T %E" | grep -E 'JOBID|htr-r6|htr-r7' || true
  exit 0
fi

[[ -d "$SRC/gm-htr-r6-core" ]] || { echo "ERROR: missing $SRC/gm-htr-r6-core" >&2; exit 1; }
CKPT=$(ls -t "$SRC/gm-htr-r6-core"/checkpoint_*.ckpt 2>/dev/null | grep -v abort | head -1 || true)
[[ -n "$CKPT" ]] || { echo "ERROR: no r6 checkpoint — run r6_core_retrain first" >&2; exit 1; }

log "latest ckpt: $(basename "$CKPT")"

cd "$SRC"
R6=$(sbatch --parsable -A hum260002p "$SCRIPTS/r6_core_resume.sbatch")
log "submitted htr-r6-core-r job $R6 (48h chunk; auto-chains until early-stop)"
log "r7-full will auto-submit from r6 sbatch when early-stop exports best mlmodel"
echo ""
squeue -u "$USER" -o "%.10i %.16j %.8T %.12M %E" | grep -E 'JOBID|htr-r6|htr-r7' || true
REMOTE
