#!/bin/bash
#SBATCH -J htr-r6-lite
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 24:00:00
#SBATCH -A hum260002p
#SBATCH -o %x-%j.out
# Light fine-tune from sloppy r5 — prefer r6_core_retrain.sbatch + r7_full_retrain.sbatch.
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
source "$SRC/../kraken-venv/bin/activate"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

python -c "import torch; print('CUDA available:', torch.cuda.is_available())"

# Idempotent: regularize corpus + symlink r6 manifests
bash "$SRC/scripts/bridges_latin_corpus_prep.sh"

ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  -i "$SRC/gm-htr-r5-best.mlmodel" --resize union -f page \
  -q early --lag 20 --min-epochs 5 -N 100 -B 16 \
  -r 0.00001 --schedule cosine --augment \
  -t "$GT/full_train_manifest.txt" -e "$GT/full_val_manifest.txt" \
  -o "$SRC/gm-htr-r6"
