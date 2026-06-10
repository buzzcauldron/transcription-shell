#!/bin/bash
#SBATCH -J htr-prep-core
#SBATCH -p RM-shared
#SBATCH -N 1
#SBATCH --ntasks-per-node=8
#SBATCH -t 02:00:00
#SBATCH -A hum260002p
#SBATCH -o %x-%j.out
# CPU-only prep: regularize corpus + build core_train/val manifests (no Bullinger).
# Submit before r6-core:
#   PREP_JOB=$(sbatch --parsable scripts/bridges_prep_core.sbatch)
#   sbatch --dependency=afterok:$PREP_JOB scripts/r6_core_retrain.sbatch
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src

# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"

export SKIP_BULLINGER_EXTRACT=1
bash "$SRC/scripts/bridges_latin_corpus_prep.sh"
