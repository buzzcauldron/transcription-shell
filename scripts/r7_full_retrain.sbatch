#!/bin/bash
#SBATCH -J htr-r7-full
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/%x-%j.out
#SBATCH --signal=B:USR1@300
# Phase 2: full regularized corpus + Bullinger, charset union from r6-core.
# Self-chains on wall timeout; finalizes when early-stop fires.
# First run (no checkpoint): sbatch --dependency=afterok:<r6-jobid> scripts/r7_full_retrain.sbatch
# Resume manually:           sbatch scripts/r7_full_retrain.sbatch
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
BASE="$SRC/gm-htr-r6-core_best.mlmodel"
OUT="$SRC/gm-htr-r7-full"
EXPORT="$SRC/gm-htr-r7-full_best.mlmodel"
CHAINED=0

chain_self() {
  [[ "$CHAINED" -eq 1 ]] && return 0
  local next
  next=$(sbatch --parsable --dependency=afterany:"$SLURM_JOB_ID" -A hum260002p "$SRC/scripts/r7_full_retrain.sbatch")
  echo "[r7-full] chaining next 48h chunk job $next (afterany:$SLURM_JOB_ID)"
  CHAINED=1
}

on_exit() {
  local ec=$?
  set +e
  # Check for early-stop: ketos saves _best.mlmodel on natural completion.
  local early=0
  for candidate in \
    "$OUT.mlmodel_best.mlmodel" \
    "${OUT}_best.mlmodel" \
    "$OUT-best.mlmodel"; do
    if [[ -f "$candidate" ]]; then
      [[ "$(readlink -f "$candidate")" != "$(readlink -f "$EXPORT")" ]] && cp -f "$candidate" "$EXPORT"
      echo "[r7-full] early-stop: exported $EXPORT"
      early=1
      break
    fi
  done

  if [[ "$early" -eq 1 ]]; then
    bash "$SRC/scripts/bridges_post_training.sh" \
      --model-name gm-htr-r7-full \
      --model-path "$EXPORT" \
      --val-manifest "$GT/full_val_manifest.txt" \
      --round r7-full \
      --base gm-htr-r6-core_best \
      --notes "Phase 2: full corpus + Bullinger, resize union, Bridges2 GPU-shared V100" \
      2>/dev/null || true
  else
    # Timeout or crash — export best checkpoint so far, then chain.
    bash "$SRC/scripts/bridges_export_kraken_checkpoint.sh" "$OUT" "$EXPORT" 2>/dev/null || true
    chain_self
  fi
  exit "$ec"
}
trap on_exit EXIT

# USR1 fires 300s before wall: submit next chunk while ketos is still running.
# The current job will be killed by Slurm; EXIT trap runs afterward.
trap 'echo "[r7-full] USR1: ~5min to wall; pre-chaining"; chain_self' USR1

cd "$SRC"
module load anaconda3 2>/dev/null || true

# Rebuild full manifests only on first run (manifest files persist across chunks).
if [[ -s "$GT/full_train_manifest.txt" ]] && [[ -s "$GT/metadata.jsonl" ]]; then
  echo "[r7-full] using existing full manifests"
else
  echo "[r7-full] running full corpus prep (with Bullinger if present)"
  bash "$SRC/scripts/bridges_latin_corpus_prep.sh"
fi

bash "$SRC/scripts/bridges_fix_kraken_numpy.sh"
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

python -c "import torch; print('CUDA:', torch.cuda.is_available())"

# Resolve base model fallbacks.
[[ -f "$BASE" ]] || BASE="$SRC/gm-htr-r6-core.mlmodel_best.mlmodel"
if [[ ! -f "$BASE" ]] && [[ -d "$SRC/gm-htr-r6-core" ]]; then
  echo "[r7-full] exporting r6 best from latest checkpoint"
  bash "$SRC/scripts/bridges_export_kraken_checkpoint.sh" \
    "$SRC/gm-htr-r6-core" "$SRC/gm-htr-r6-core_best.mlmodel" || true
  BASE="$SRC/gm-htr-r6-core_best.mlmodel"
fi
[[ -f "$BASE" ]] || { echo "Missing r6-core best model"; exit 1; }

# Resume from existing checkpoint if present; otherwise start fresh.
CKPT=$(ls -t "$OUT"/checkpoint_*.ckpt 2>/dev/null | grep -v abort | head -1 || true)
if [[ -n "$CKPT" ]]; then
  echo "[r7-full] resuming from ckpt=$CKPT"
  echo "[r7-full] train=$(wc -l < "$GT/full_train_manifest.txt") val=$(wc -l < "$GT/full_val_manifest.txt")"
  ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
    --resume "$CKPT" -f page \
    -q early --lag 20 --min-epochs 5 -N 100 -B 16 \
    -r 0.00001 --schedule cosine --augment \
    -t "$GT/full_train_manifest.txt" -e "$GT/full_val_manifest.txt" \
    -o "$OUT"
else
  echo "[r7-full] first run: base=$BASE"
  echo "[r7-full] train=$(wc -l < "$GT/full_train_manifest.txt") val=$(wc -l < "$GT/full_val_manifest.txt")"
  ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
    -i "$BASE" --resize union -f page \
    -q early --lag 20 --min-epochs 5 -N 100 -B 16 \
    -r 0.00001 --schedule cosine --augment \
    -t "$GT/full_train_manifest.txt" -e "$GT/full_val_manifest.txt" \
    -o "$OUT"
fi
