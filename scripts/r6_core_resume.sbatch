#!/bin/bash
#SBATCH -J htr-r6-core-r
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/%x-%j.out
#SBATCH --signal=B:USR1@300
# Resume r6-core from the latest Lightning checkpoint (48h GPU-shared chunks).
# Self-chains on timeout until early-stop; then submits r7-full.
# Manual chain: sbatch --dependency=afterany:<prior-jobid> scripts/r6_core_resume.sbatch
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
OUT="$SRC/gm-htr-r6-core"
EXPORT="$SRC/gm-htr-r6-core_best.mlmodel"
CHAINED=0
R7_SUBMITTED=0

export_r6_best_from_ckpt() {
  bash "$SRC/scripts/bridges_export_kraken_checkpoint.sh" "$OUT" "$EXPORT" 2>/dev/null || true
}

submit_r7_if_ready() {
  [[ -s "$EXPORT" ]] || return 0
  if squeue -u "$USER" -h -o "%j %T" | awk '$1=="htr-r7-full" && ($2=="RUNNING" || $2=="PENDING") {found=1} END{exit !found}'; then
    echo "[r6-core-resume] r7-full already queued"
    return 0
  fi
  local r7
  r7=$(sbatch --parsable -A hum260002p "$SRC/scripts/r7_full_retrain.sbatch")
  echo "[r6-core-resume] submitted r7-full job $r7 (r6 best ready)"
  R7_SUBMITTED=1
}

on_exit() {
  local ec=$?
  set +e
  local early=0
  for candidate in \
    "$OUT.mlmodel_best.mlmodel" \
    "$OUT"_best.mlmodel \
    "$OUT-best.mlmodel"; do
    if [[ -f "$candidate" ]]; then
      if [[ "$(readlink -f "$candidate")" != "$(readlink -f "$EXPORT")" ]]; then
        cp -f "$candidate" "$EXPORT"
      fi
      echo "[r6-core-resume] exported $EXPORT (early-stop)"
      early=1
      break
    fi
  done

  if [[ "$early" -eq 1 ]]; then
    submit_r7_if_ready
  else
    export_r6_best_from_ckpt
    if [[ "$CHAINED" -eq 0 ]] && [[ -n "${SLURM_JOB_ID:-}" ]]; then
      local next
      next=$(sbatch --parsable --dependency=afterany:"$SLURM_JOB_ID" -A hum260002p "$SRC/scripts/r6_core_resume.sbatch")
      echo "[r6-core-resume] chaining next 48h chunk job $next (afterany:$SLURM_JOB_ID)"
      CHAINED=1
    fi
  fi
  exit "$ec"
}
trap on_exit EXIT
# USR1 fires 300s before wall: pre-chain while ketos is still running.
trap 'echo "[r6-core-resume] USR1: ~5min to wall; pre-chaining"; chain_self_now' USR1

chain_self_now() {
  [[ "$CHAINED" -eq 1 ]] && return 0
  if [[ -n "${SLURM_JOB_ID:-}" ]]; then
    local next
    next=$(sbatch --parsable --dependency=afterany:"$SLURM_JOB_ID" -A hum260002p "$SRC/scripts/r6_core_resume.sbatch")
    echo "[r6-core-resume] pre-chained next chunk job $next (USR1 handler)"
    CHAINED=1
  fi
}

module load anaconda3 2>/dev/null || true
bash "$SRC/scripts/bridges_fix_kraken_numpy.sh"
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

CKPT=$(ls -t "$OUT"/checkpoint_*.ckpt 2>/dev/null | grep -v abort | head -1 || true)
[[ -n "$CKPT" ]] || { echo "No checkpoint in $OUT — run r6_core_retrain.sbatch first"; exit 1; }

echo "[r6-core-resume] ckpt=$CKPT"
echo "[r6-core-resume] train=$(wc -l < "$GT/core_train_manifest.txt") val=$(wc -l < "$GT/core_val_manifest.txt")"

export_r6_best_from_ckpt || true

ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  --resume "$CKPT" -f page \
  -q early --lag 25 --min-epochs 10 -N 150 -B 16 \
  -r 0.00005 --schedule cosine --augment \
  -t "$GT/core_train_manifest.txt" -e "$GT/core_val_manifest.txt" \
  -o "$OUT"
