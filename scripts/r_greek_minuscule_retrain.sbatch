#!/bin/bash
#SBATCH -J htr-greek-min
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/%x-%j.out
# Greek Byzantine minuscule HTR specialist.
# Fine-tune PTA 9–12c NFC seed (or prior Greek ckpt) on Athos + EPARCHOS + Palatine + HPGTR.
#
# Prereq: htr-corpora-greek on Ocean (rsync_greek_corpora_to_bridges.sh) + seed mlmodel.
#   sbatch scripts/r_greek_minuscule_retrain.sbatch
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/greek-corpus-gt"
BASE="$SRC/greek_minuscule_s9-12_NFC.mlmodel"
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
      echo "[greek-min] exported $EXPORT (early-stop)"
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
      --notes "Byzantine Greek minuscule: Athos+EPARCHOS+Palatine(+HPGTR); PTA seed" || true
  elif [[ "$CHAINED" -eq 0 ]] && [[ -n "${SLURM_JOB_ID:-}" ]]; then
    local next
    next=$(sbatch --parsable --dependency=afterany:"$SLURM_JOB_ID" -A hum260002p \
      "$SRC/scripts/r_greek_minuscule_resume.sbatch")
    echo "[greek-min] chaining resume job $next"
    CHAINED=1
  fi
  exit "$ec"
}
trap on_exit EXIT

cd "$SRC"
module load anaconda3 2>/dev/null || true

if [[ ! -s "$GT/greek_minuscule_train_manifest.txt" ]]; then
  echo "[greek-min] building greek-corpus-gt"
  bash "$SRC/scripts/bridges_greek_corpus_prep.sh"
fi

bash "$SRC/scripts/bridges_fix_kraken_numpy.sh"
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

python -c "import torch; print('CUDA:', torch.cuda.is_available())"

[[ -f "$BASE" ]] || BASE="$SRC/greek_minuscule_s9-12_NFC.mlmodel"
[[ -f "$BASE" ]] || {
  echo "Missing PTA seed $SRC/greek_minuscule_s9-12_NFC.mlmodel"
  echo "  Download Zenodo 15838142 and rsync to Ocean SRC/"
  exit 1
}

[[ -s "$GT/greek_minuscule_train_manifest.txt" ]] || {
  echo "Missing greek_minuscule_train_manifest.txt"; exit 1;
}

n_train=$(wc -l < "$GT/greek_minuscule_train_manifest.txt")
n_val=$(wc -l < "$GT/greek_minuscule_val_manifest.txt")
echo "[greek-min] base=$BASE"
echo "[greek-min] train=$n_train val=$n_val"

# Fresh charset from Greek GT (union with PTA seed).
ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  -i "$BASE" --resize union -f page \
  -q early --lag 20 --min-epochs 5 -N 100 -B 12 \
  -r 0.00001 --schedule cosine --augment \
  -t "$GT/greek_minuscule_train_manifest.txt" -e "$GT/greek_minuscule_val_manifest.txt" \
  -o "$OUT"

for candidate in \
  "$OUT.mlmodel_best.mlmodel" \
  "$OUT"_best.mlmodel \
  "$OUT-best.mlmodel"; do
  if [[ -f "$candidate" ]]; then
    cp -f "$candidate" "$EXPORT"
    echo "[greek-min] exported $EXPORT"
    break
  fi
done
