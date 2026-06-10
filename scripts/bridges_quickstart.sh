#!/usr/bin/env bash
# Submit the full r6->r7 training chain as proper SLURM jobs (no login-node work).
#
# Run from any Bridges login node:
#   bash /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/scripts/bridges_quickstart.sh
#
# What it submits:
#   1. htr-r6-core  (GPU-shared V100, 48h) -- prep on compute node + fine-tune from r2
#   2. htr-r7-full  (GPU-shared V100, 48h) -- full prep + fine-tune from r6-core
# r7 waits for r6 via afterok dependency.

set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
SCRIPTS="$SRC/scripts"

for f in r6_core_retrain.sbatch r7_full_retrain.sbatch; do
  [[ -f "$SCRIPTS/$f" ]] || { echo "ERROR: missing $SCRIPTS/$f" >&2; exit 1; }
done

echo "[quickstart] submitting r6-core..."
R6=$(sbatch --parsable "$SCRIPTS/r6_core_retrain.sbatch")
echo "[quickstart] r6-core job: $R6"

echo "[quickstart] submitting r7-full (depends on $R6)..."
R7=$(sbatch --parsable --dependency=afterok:"$R6" "$SCRIPTS/r7_full_retrain.sbatch")
echo "[quickstart] r7-full job: $R7"

echo ""
echo "[quickstart] chain submitted:"
echo "  r6-core  $R6  (GPU-shared, includes corpus prep)"
echo "  r7-full  $R7  (GPU-shared, afterok:$R6, includes full prep + Bullinger)"
echo ""
echo "Monitor: squeue -u sstrickland"
echo "Logs:    tail -f htr-r6-core-${R6}.out"
