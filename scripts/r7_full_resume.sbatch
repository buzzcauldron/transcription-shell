#!/bin/bash
#SBATCH -J htr-r7-full-r
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o %x-%j.out
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
OUT="$SRC/gm-htr-r7-full"

cd "$SRC"
module load anaconda3 2>/dev/null || true
bash "$SRC/scripts/bridges_fix_kraken_numpy.sh" 2>/dev/null || true
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Prefer numbered checkpoints; abort.ckpt is often newest by mtime but not a good resume.
CKPT=$(ls -t "$OUT"/checkpoint_[0-9]*.ckpt 2>/dev/null | head -1 || true)
[[ -n "$CKPT" ]] || CKPT=$(ls -t "$OUT"/checkpoint_*.ckpt 2>/dev/null | head -1 || true)
[[ -n "$CKPT" ]] || { echo "No checkpoint in $OUT"; exit 1; }
echo "[r7] resume=$CKPT"

ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  --resume "$CKPT" --resize union -f page \
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
    break
  fi
done
