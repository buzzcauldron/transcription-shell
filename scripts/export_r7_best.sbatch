#!/bin/bash
#SBATCH -J export-r7
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 00:30:00
#SBATCH -A hum260002p
#SBATCH -o %x-%j.out
set -euo pipefail
SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
cd "$SRC"
source scripts/bridges_kraken_activate.sh
bash scripts/bridges_export_kraken_checkpoint.sh "$SRC/gm-htr-r7-full" "$SRC/gm-htr-r7-full_best.mlmodel"
ls -lah "$SRC/gm-htr-r7-full_best.mlmodel"
