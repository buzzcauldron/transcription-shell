#!/bin/bash
#SBATCH -J htr-r7-full
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o %x-%j.out
# Phase 2: full regularized corpus + Bullinger, charset union from r6-core.
# Submit after r6-core finishes:
#   sbatch --dependency=afterok:<r6-core-jobid> scripts/r7_full_retrain.sbatch
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
BASE="$SRC/gm-htr-r6-core_best.mlmodel"
OUT="$SRC/gm-htr-r7-full"

# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

python -c "import torch; print('CUDA:', torch.cuda.is_available())"

# Rebuild full manifests with Bullinger on this compute node.
bash "$SRC/scripts/bridges_latin_corpus_prep.sh"

[[ -f "$BASE" ]] || BASE="$SRC/gm-htr-r6-core.mlmodel_best.mlmodel"
[[ -f "$BASE" ]] || { echo "Missing r6-core best model at $SRC/gm-htr-r6-core_best.mlmodel"; exit 1; }

echo "[r7-full] base=$BASE"
echo "[r7-full] train=$(wc -l < "$GT/full_train_manifest.txt") val=$(wc -l < "$GT/full_val_manifest.txt")"

ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  -i "$BASE" --resize union -f page \
  -q early --lag 20 --min-epochs 5 -N 100 -B 16 \
  -r 0.00001 --schedule cosine --augment \
  -t "$GT/full_train_manifest.txt" -e "$GT/full_val_manifest.txt" \
  -o "$OUT"

for candidate in \
  "$OUT.mlmodel_best.mlmodel" \
  "$OUT"_best.mlmodel \
  "$OUT-best.mlmodel"; do
  if [[ -f "$candidate" ]]; then
    cp -f "$candidate" "$SRC/gm-htr-r7-full_best.mlmodel"
    echo "[r7-full] exported $SRC/gm-htr-r7-full_best.mlmodel"
    break
  fi
done
