#!/usr/bin/env bash
# Chain the tail of the HTR pipeline: r7 → anglicana → r8-kraken → r8-trocr.
# r6 must already be queued/running; pass its job id or auto-detect.
#
#   bash scripts/bridges_chain_htr_tail.sh
#   bash scripts/bridges_chain_htr_tail.sh 41371493
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGIN="${BRIDGES_LOGIN:-bridges2}"
SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
R6="${1:-}"

bash "$SCRIPT_DIR/sync_scripts_to_bridges.sh"

ssh -o BatchMode=yes "$LOGIN" bash -s <<REMOTE
set -euo pipefail
SRC="$SRC"
R6="${R6}"

if [[ -z "\$R6" ]]; then
  R6=\$(squeue -u "\$USER" -h -o "%i %j %T" | awk '\$2=="htr-r6-core" && (\$3=="RUNNING" || \$3=="PENDING") {print \$1; exit}')
fi
[[ -n "\$R6" ]] || { echo "ERROR: no running/pending htr-r6-core — pass job id or start bridges_start.sh first" >&2; exit 1; }

# r7: reuse if already waiting on this r6
R7=\$(squeue -u "\$USER" -h -o "%i %j %r" | awk -v r6="\$R6" '\$2=="htr-r7-full" && \$3 ~ r6 {print \$1; exit}')
if [[ -z "\$R7" ]]; then
  R7=\$(cd "\$SRC" && sbatch --parsable --dependency=afterok:"\$R6" scripts/r7_full_retrain.sbatch)
  echo "[chain] r7-full job \$R7 (afterok:\$R6)"
else
  echo "[chain] r7-full job \$R7 (existing)"
fi

# anglicana: must follow r7 (not r6 in parallel)
while IFS= read -r jid; do
  [[ -n "\$jid" ]] && scancel "\$jid" || true
done < <(squeue -u "\$USER" -h -o "%i %j" | awk '\$2=="htr-anglicana" {print \$1}')
ANG=\$(cd "\$SRC" && sbatch --parsable --dependency=afterok:"\$R7" scripts/r_anglicana_legal.sbatch)
echo "[chain] anglicana job \$ANG (afterok:\$R7)"

R8K=\$(cd "\$SRC" && sbatch --parsable --dependency=afterok:"\$ANG" scripts/r8_gothic_bible_retrain.sbatch)
echo "[chain] r8-gothic-kraken job \$R8K (afterok:\$ANG)"

R8T=\$(cd "\$SRC" && sbatch --parsable --dependency=afterok:"\$R8K" scripts/r8_trocr_gothic_bible.sbatch)
echo "[chain] r8-trocr job \$R8T (afterok:\$R8K)"

echo ""
squeue -u "\$USER" -o "%.10i %.18j %.8T %.10h %E" | grep -E 'JOBID|htr-r6|htr-r7|anglican|r8-gothic|trocr-r8' || true
REMOTE
