#!/bin/bash
# DEPRECATED — RM partition requires QoS not available to this allocation (hum260002p).
# Prep now runs inline inside r6_core_retrain.sbatch on GPU-shared.
# Use bridges_start.sh instead of this file.
#SBATCH -J htr-prep-core
#SBATCH -p RM
#SBATCH -N 1
#SBATCH --ntasks-per-node=16
#SBATCH -t 02:00:00
#SBATCH -A hum260002p
#SBATCH -o %x-%j.out
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src

# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"

export SKIP_BULLINGER_EXTRACT=1
bash "$SRC/scripts/bridges_latin_corpus_prep.sh"
