#!/bin/bash
# Bridges GPU-shared efficiency sample — same pipeline shape as other hosts;
# Settings tuned via AUTO_EFFICIENCY (batch_parallel=1 on single GPU).
# Login node is submit-only; this script runs on the allocated GPU node.
#
#SBATCH -J eff-htr
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:1
#SBATCH --qos=gpuinteract
#SBATCH -N 1
#SBATCH --ntasks-per-node=4
#SBATCH -t 00:20:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/%x-%j.out

set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
FIX="$SRC/benchmark/efficiency_fixture"
OUT_ROOT="$SRC/benchmark/results/efficiency"
cd "$SRC"

module load anaconda3 2>/dev/null || true
bash "$SRC/scripts/bridges_fix_kraken_numpy.sh" 2>/dev/null || true
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export PYTHONPATH="$SRC${PYTHONPATH:+:$PYTHONPATH}"
export TRANSCRIBER_SHELL_AUTO_EFFICIENCY=1
# Isolate GPU HTR wall time for this microbench (production default remains correct).
export TRANSCRIBER_SHELL_LLM_MODE=off
export TRANSCRIBER_SHELL_HTR_COMBINATION=kraken_htr_only
export TRANSCRIBER_SHELL_LINEATION_BACKEND=kraken
export TRANSCRIBER_SHELL_REUSE_LINES_XML=true

if [[ -f "$SRC/gm-htr-computus_best.mlmodel" ]]; then
  export TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH="$SRC/gm-htr-computus_best.mlmodel"
elif [[ -f "$SRC/gm-htr-r5-best.mlmodel" ]]; then
  export TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH="$SRC/gm-htr-r5-best.mlmodel"
else
  echo "ERROR: no HTR .mlmodel under $SRC" >&2
  exit 1
fi
if [[ -f "$FIX/kraken-merged-seg.mlmodel_best.mlmodel" ]]; then
  export TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH="$FIX/kraken-merged-seg.mlmodel_best.mlmodel"
elif [[ -f "$SRC/kraken-merged-seg.mlmodel_best.mlmodel" ]]; then
  export TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH="$SRC/kraken-merged-seg.mlmodel_best.mlmodel"
fi

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$OUT_ROOT/${STAMP}_bridges_gpu"
mkdir -p "$OUT"
export OUT_DIR="$OUT"
export FIX_DIR="$FIX"

n_img=$(find "$FIX" -maxdepth 1 \( -name '*.jpg' -o -name '*.png' \) 2>/dev/null | wc -l | tr -d ' ')
if [[ "${n_img:-0}" -lt 1 ]]; then
  echo "ERROR: missing fixture pages in $FIX — run scripts/submit_bridges_efficiency.sh first" >&2
  exit 1
fi

python "$SRC/scripts/_eff_htr_run.py"
