#!/bin/bash
#SBATCH -J htr-r6-core-r
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o %x-%j.out
# Resume r6-core from the latest Lightning checkpoint (48h GPU-shared chunks).
#   sbatch --dependency=afterany:<prior-jobid> scripts/r6_core_resume.sbatch
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
OUT="$SRC/gm-htr-r6-core"

source "$SRC/../kraken-venv/bin/activate"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

CKPT=$(ls -t "$OUT"/checkpoint_*.ckpt 2>/dev/null | head -1 || true)
[[ -n "$CKPT" ]] || { echo "No checkpoint in $OUT — run r6_core_retrain.sbatch first"; exit 1; }

echo "[r6-core-resume] ckpt=$CKPT"
echo "[r6-core-resume] train=$(wc -l < "$GT/core_train_manifest.txt") val=$(wc -l < "$GT/core_val_manifest.txt")"

ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  --resume "$CKPT" -f page \
  -q early --lag 25 --min-epochs 10 -N 150 -B 16 \
  -r 0.00005 --schedule cosine --augment \
  -t "$GT/core_train_manifest.txt" -e "$GT/core_val_manifest.txt" \
  -o "$OUT"

for candidate in \
  "$OUT.mlmodel_best.mlmodel" \
  "$OUT"_best.mlmodel \
  "$OUT-best.mlmodel"; do
  if [[ -f "$candidate" ]]; then
    cp -f "$candidate" "$SRC/gm-htr-r6-core_best.mlmodel"
    echo "[r6-core-resume] exported $SRC/gm-htr-r6-core_best.mlmodel"
    break
  fi
done
