#!/bin/bash
#SBATCH -J comma-rerec
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=4
#SBATCH -t 12:00:00
#SBATCH -A hum260002p
#SBATCH -o %x-%j.out
# CoMMA recognition-only pilot. Requires expanded /ocean (~30G comma-jsonl + page cache).
# Submit AFTER: (1) extra storage live, (2) r7 retrain done, (3) comma_acquire.sh
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
COMMA_ROOT=/ocean/projects/hum260002p/sstrickland/comma-rerecognition
MODEL="${MODEL:-$SRC/gm-htr-r7-full_best.mlmodel}"
SEG="${SEG_MODEL:-$SRC/kraken-merged-seg_best.mlmodel}"
PILOT="$COMMA_ROOT/pilot-$(date +%Y%m%d)"

source "$SRC/../kraken-venv/bin/activate"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

[[ -d "$COMMA_ROOT/raw/comma-jsonl" ]] || {
  echo "Run: COMMA_ROOT=$COMMA_ROOT bash $SRC/scripts/comma_acquire.sh"; exit 1;
}
[[ -f "$MODEL" ]] || {
  echo "Missing HTR model $MODEL — finish r6/r7 retrain first"; exit 1;
}

# Scale these up once memory/storage is comfortable
MAX_MS="${MAX_MS:-100}"
MAX_PAGES="${MAX_PAGES:-5}"

python3 "$SRC/scripts/comma_recognition_pass.py" \
  --comma-jsonl "$COMMA_ROOT/raw/comma-jsonl" \
  --model "$MODEL" \
  --seg-model "$SEG" \
  --out-dir "$PILOT" \
  --language-filter latin \
  --max-manuscripts "$MAX_MS" \
  --max-pages-per-ms "$MAX_PAGES" \
  --device cuda:0

echo "[comma] results: $PILOT/rerecognition.jsonl"
echo "[comma] TRAINING FIREWALL: never copy $COMMA_ROOT into htr-corpora/"
