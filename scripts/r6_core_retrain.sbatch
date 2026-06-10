#!/bin/bash
#SBATCH -J htr-r6-core
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o %x-%j.out
# Phase 1: clean medieval Latin from r2. GPU-shared max walltime is 48h.
# If early-stop has not fired by 48h, chain: sbatch --dependency=afterany:<jobid> scripts/r6_core_resume.sbatch
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
BASE="$SRC/gm-htr-r2.mlmodel_best.mlmodel"
OUT="$SRC/gm-htr-r6-core"

# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

python -c "import torch; print('CUDA:', torch.cuda.is_available())"

# Run corpus prep on this compute node (SKIP_BULLINGER -- not needed for core train).
export SKIP_BULLINGER_EXTRACT=1
bash "$SRC/scripts/bridges_latin_corpus_prep.sh"

[[ -f "$BASE" ]] || { echo "Missing base model: $BASE"; exit 1; }
[[ -s "$GT/core_train_manifest.txt" ]] || { echo "Prep failed: no core manifests"; exit 1; }

echo "[r6-core] base=$BASE"
echo "[r6-core] train=$(wc -l < "$GT/core_train_manifest.txt") val=$(wc -l < "$GT/core_val_manifest.txt")"

ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  -i "$BASE" -f page \
  -q early --lag 25 --min-epochs 10 -N 150 -B 16 \
  -r 0.00005 --schedule cosine --augment \
  -t "$GT/core_train_manifest.txt" -e "$GT/core_val_manifest.txt" \
  -o "$OUT"

# Export best for phase 2 (ketos naming: <prefix>.mlmodel_best.mlmodel)
for candidate in \
  "$OUT.mlmodel_best.mlmodel" \
  "$OUT"_best.mlmodel \
  "$OUT-best.mlmodel"; do
  if [[ -f "$candidate" ]]; then
    cp -f "$candidate" "$SRC/gm-htr-r6-core_best.mlmodel"
    echo "[r6-core] exported $SRC/gm-htr-r6-core_best.mlmodel"
    break
  fi
done
