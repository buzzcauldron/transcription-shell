#!/bin/bash
#SBATCH -J htr-r8-gothic
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/%x-%j.out
# Gothic book Latin specialist (LAD 1.3–like recipe): Paris Bible + CREMMA/HTRomance.
# Fine-tune from gm-htr-r5-best (fallback gm-htr-r2_best).
#
# Prereq: bridges_latin_corpus_prep.sh (ALTO→PAGE + gothic_bible_* manifests).
#   sbatch scripts/r8_gothic_bible_retrain.sbatch
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
BASE="$SRC/gm-htr-r5-best.mlmodel"
OUT="$SRC/gm-htr-r8-gothic-bible"

cd "$SRC"
module load anaconda3 2>/dev/null || true

if [[ ! -s "$GT/gothic_bible_train_manifest.txt" ]]; then
  echo "[r8-gothic] building manifests (Paris Bible ALTO→PAGE + split)"
  bash "$SRC/scripts/bridges_latin_corpus_prep.sh"
fi

bash "$SRC/scripts/bridges_fix_kraken_numpy.sh"
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

python -c "import torch; print('CUDA:', torch.cuda.is_available())"

[[ -f "$BASE" ]] || BASE="$SRC/gm-htr-r5-best.mlmodel"
[[ -f "$BASE" ]] || BASE="$SRC/gm-htr-r2.mlmodel_best.mlmodel"
[[ -f "$BASE" ]] || { echo "Missing base model (gm-htr-r5-best or gm-htr-r2_best)"; exit 1; }

[[ -s "$GT/gothic_bible_train_manifest.txt" ]] || {
  echo "Missing gothic_bible_train_manifest.txt — run regularize + split_retrain_manifests"; exit 1;
}

echo "[r8-gothic] base=$BASE"
echo "[r8-gothic] train=$(wc -l < "$GT/gothic_bible_train_manifest.txt") val=$(wc -l < "$GT/gothic_bible_val_manifest.txt")"
echo "[r8-gothic] paris-bible lines: $(grep -c paris-bible "$GT/metadata.jsonl" 2>/dev/null || echo 0)"

ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  -i "$BASE" --resize union -f page \
  -q early --lag 20 --min-epochs 5 -N 100 -B 16 \
  -r 0.00001 --schedule cosine --augment \
  -t "$GT/gothic_bible_train_manifest.txt" -e "$GT/gothic_bible_val_manifest.txt" \
  -o "$OUT"

for candidate in \
  "$OUT.mlmodel_best.mlmodel" \
  "$OUT"_best.mlmodel \
  "$OUT-best.mlmodel"; do
  if [[ -f "$candidate" ]]; then
    cp -f "$candidate" "$SRC/gm-htr-r8-gothic-bible_best.mlmodel"
    echo "[r8-gothic] exported $SRC/gm-htr-r8-gothic-bible_best.mlmodel"
    break
  fi
done

bash "$SRC/scripts/bridges_post_training.sh" \
  --model-name gm-htr-r8-gothic-bible \
  --model-path "$SRC/gm-htr-r8-gothic-bible_best.mlmodel" \
  --val-manifest "$GT/gothic_bible_val_manifest.txt" \
  --round r8-gothic-bible \
  --base gm-htr-r5-best \
  --notes "Gothic book Latin: Paris Bible PBP 1.0 + CREMMA/HTRomance; LAD-style specialist"
