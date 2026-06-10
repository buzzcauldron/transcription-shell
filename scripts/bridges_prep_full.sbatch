#!/bin/bash
#SBATCH -J htr-prep-full
#SBATCH -p RM-shared
#SBATCH -N 1
#SBATCH --ntasks-per-node=8
#SBATCH -t 03:00:00
#SBATCH -A hum260002p
#SBATCH -o %x-%j.out
# CPU-only prep: regularize corpus + build full_train/val manifests (includes Bullinger extract).
# Submit before r7-full, chained after r6-core:
#   PREP_FULL=$(sbatch --parsable --dependency=afterok:$R6_JOB scripts/bridges_prep_full.sbatch)
#   sbatch --dependency=afterok:$PREP_FULL scripts/r7_full_retrain.sbatch
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src

# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"

bash "$SRC/scripts/bridges_latin_corpus_prep.sh"
