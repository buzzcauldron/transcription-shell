#!/bin/bash
#SBATCH -J export-greek
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 00:30:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/%x-%j.out
set -euo pipefail
SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
module load anaconda3 2>/dev/null || true
bash "$SRC/scripts/bridges_fix_kraken_numpy.sh"
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
bash "$SRC/scripts/bridges_export_kraken_checkpoint.sh" \
  "$SRC/gm-htr-greek-minuscule" \
  "$SRC/gm-htr-greek-minuscule_best.mlmodel"
ls -lh "$SRC/gm-htr-greek-minuscule_best.mlmodel"
