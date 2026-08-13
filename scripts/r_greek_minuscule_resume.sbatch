#!/bin/bash
#SBATCH -J htr-greek-min-r
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/%x-%j.out
# Resume Greek minuscule fine-tune (48h GPU-shared chunks; auto-chain).
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/greek-corpus-gt"
OUT="$SRC/gm-htr-greek-minuscule"
EXPORT="$SRC/gm-htr-greek-minuscule_best.mlmodel"
CHAINED=0

on_exit() {
  local ec=$?
  set +e
  local early=0
  for candidate in \
    "$OUT.mlmodel_best.mlmodel" \
    "$OUT"_best.mlmodel \
    "$OUT-best.mlmodel"; do
    if [[ -f "$candidate" ]]; then
      cp -f "$candidate" "$EXPORT"
      echo "[greek-min-r] exported $EXPORT"
      early=1
      break
    fi
  done
  if [[ "$early" -eq 1 ]]; then
    bash "$SRC/scripts/bridges_post_training.sh" \
      --model-name gm-htr-greek-minuscule \
      --model-path "$EXPORT" \
      --val-manifest "$GT/greek_minuscule_val_manifest.txt" \
      --round greek-minuscule \
      --base greek_minuscule_s9-12_NFC \
      --notes "Greek minuscule resume; early-stop" || true
  elif [[ "$CHAINED" -eq 0 ]] && [[ -n "${SLURM_JOB_ID:-}" ]]; then
    local next
    next=$(sbatch --parsable --dependency=afterany:"$SLURM_JOB_ID" -A hum260002p \
      "$SRC/scripts/r_greek_minuscule_resume.sbatch")
    echo "[greek-min-r] chaining next chunk $next"
    CHAINED=1
  else
    bash "$SRC/scripts/bridges_export_kraken_checkpoint.sh" "$OUT" "$EXPORT" 2>/dev/null || true
  fi
  exit "$ec"
}
trap on_exit EXIT

cd "$SRC"
module load anaconda3 2>/dev/null || true

[[ -s "$GT/greek_minuscule_train_manifest.txt" ]] || bash "$SRC/scripts/bridges_greek_corpus_prep.sh"

bash "$SRC/scripts/bridges_fix_kraken_numpy.sh"
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

CKPT=$(ls -t "$OUT"/checkpoint_*.ckpt 2>/dev/null | grep -v abort | head -1 || true)
[[ -n "$CKPT" ]] || { echo "No checkpoint in $OUT — run r_greek_minuscule_retrain.sbatch first"; exit 1; }

echo "[greek-min-r] ckpt=$CKPT"
ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  --resume "$CKPT" --resize union -f page \
  -q early --lag 20 --min-epochs 5 -N 100 -B 12 \
  -r 0.00001 --schedule cosine --augment \
  -t "$GT/greek_minuscule_train_manifest.txt" -e "$GT/greek_minuscule_val_manifest.txt" \
  -o "$OUT"
