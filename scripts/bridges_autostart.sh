#!/usr/bin/env bash
# Run on akdeniz after run_xfer_extras.sh finishes (same shell = reuse PSC auth if cached).
# Sets up kraken venv on Bridges login node, preps corpus, submits r6-core.
set -euo pipefail

BRIDGES_LOGIN="${BRIDGES_LOGIN:-bridges2}"
BRIDGES_DTN="${BRIDGES_DTN:-bridges2-dtn}"
PROJECT=/ocean/projects/hum260002p/sstrickland/transcriber-shell
SRC="$PROJECT/src"
SCRIPTS_LOCAL="${SCRIPTS_LOCAL:-$HOME/src/scripts}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
RSYNC=(rsync -avh -e "ssh ${SSH_OPTS[*]}")

log() { echo "[bridges-autostart] $(date -Iseconds) $*"; }

log "syncing latest scripts -> Bridges"
"${RSYNC[@]}" "$SCRIPTS_LOCAL/" "$BRIDGES_DTN:$SRC/scripts/"

if ssh "${SSH_OPTS[@]}" "$BRIDGES_LOGIN" "test -x $PROJECT/kraken-venv/bin/ketos" 2>/dev/null; then
  log "ketos already present on Bridges — skip venv install"
else
  log "rsync kraken venv from akdeniz (~8GB, faster than pip)"
  bash "$SCRIPTS_LOCAL/rsync_kraken_venv_to_bridges.sh"

  log "fix venv paths on Bridges login"
  ssh "${SSH_OPTS[@]}" "$BRIDGES_LOGIN" "bash $SRC/scripts/fix_bridges_venv_paths.sh" \
    || {
      log "rsync venv failed path fix — falling back to pip install"
      ssh "${SSH_OPTS[@]}" "$BRIDGES_LOGIN" bash -s <<REMOTE
set -euo pipefail
export PYTHONNOUSERSITE=True
module load python 2>/dev/null || module load anaconda3
nohup bash "$SRC/scripts/setup_bridges_kraken_venv.sh" > "$PROJECT/kraken-venv-setup.log" 2>&1 &
REMOTE
      log "waiting for pip venv (up to 30 min)..."
      for i in $(seq 1 60); do
        ssh "${SSH_OPTS[@]}" "$BRIDGES_LOGIN" "test -x $PROJECT/kraken-venv/bin/ketos" 2>/dev/null && break
        sleep 30
        [[ "$i" -eq 60 ]] && { log "venv TIMEOUT — see $PROJECT/kraken-venv-setup.log"; exit 1; }
      done
    }
fi
log "ketos ready"

log "running corpus prep on Bridges login"
ssh "${SSH_OPTS[@]}" "$BRIDGES_LOGIN" "export SRC=$SRC; bash $SRC/scripts/bridges_latin_corpus_prep.sh"

log "submitting r6-core GPU job"
JOB=$(ssh "${SSH_OPTS[@]}" "$BRIDGES_LOGIN" "cd $SRC && sbatch scripts/r6_core_retrain.sbatch" | awk '{print $4}')
log "submitted job $JOB"
log "monitor: ssh $BRIDGES_LOGIN 'squeue -u sstrickland; tail -f $SRC/htr-r6-core-${JOB}.out'"
