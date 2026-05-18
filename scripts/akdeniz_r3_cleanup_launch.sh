#!/usr/bin/env bash
# Copy to akdeniz and run: scp scripts/akdeniz_r3_cleanup_launch.sh seth@akdeniz.lan.cmu.edu:~/ && ssh … 'bash ~/akdeniz_r3_cleanup_launch.sh'
# Kills stuck r3 ketos, deletes gm-htr-r2.mlmodel_<n> intermediates (not *_best), starts screen r3-train.
# Ketos flags match scripts/prep_and_launch_r3.sh (--workers 8, -B 64).
set -euo pipefail

SRC="${SRC:-$HOME/src}"
VENV="${VENV:-$HOME/.venv-kraken}"

pkill -KILL -f 'keto[s].*gm-htr-r3\.mlmodel' 2>/dev/null || true
sleep 1

shopt -s nullglob
removed=0
for f in "$SRC"/gm-htr-r2.mlmodel_[0-9]*.mlmodel; do
  rm -f -- "$f"
  removed=$((removed + 1))
done
echo "Removed $removed intermediate gm-htr-r2.mlmodel_<n>.mlmodel files."

BASE="$SRC/gm-htr-r2.mlmodel_best.mlmodel"
if [[ ! -f "$BASE" ]]; then
  BASE="$SRC/gm-hf-htr_best.mlmodel"
fi
if [[ ! -f "$BASE" ]]; then
  echo "ERROR: no base model" >&2
  exit 1
fi
echo "BASE=$BASE"

rm -f "$HOME/htr-r3-done.flag"
screen -S r3-train -X quit 2>/dev/null || true

RUNNER="$HOME/_ketos_r3_inner.sh"
LOG="$HOME/htr-r3-$(date +%Y%m%d-%H%M).log"

cat > "$RUNNER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "$VENV/bin/activate"
export PYTHONUNBUFFERED=1
export PYTORCH_ALLOC_CONF=expandable_segments:True
export CUDA_MPS_PIPE_DIRECTORY=/dev/null
ketos -d cuda:0 --workers 8 --precision bf16-mixed train \\
  -i "$BASE" \\
  --resize union -f path -q early --lag 20 --min-epochs 5 -N 100 -B 64 \\
  -r 0.00005 --schedule reduceonplateau --sched-patience 5 \\
  -t "$SRC/htr-r3-train.txt" -e "$SRC/htr-r3-eval.txt" \\
  -o "$SRC/gm-htr-r3.mlmodel" \\
  2>&1 | tee "$LOG"
echo DONE >> "$HOME/htr-r3-done.flag"
EOF
chmod +x "$RUNNER"

screen -dmS r3-train bash -lc "\"$RUNNER\""
sleep 2
echo "=== screen ==="
screen -ls || true
echo "Log: $LOG"
sleep 1
tail -20 "$LOG" 2>/dev/null || true
