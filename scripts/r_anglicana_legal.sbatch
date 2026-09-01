#!/bin/bash
#SBATCH -J htr-anglicana
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/%x-%j.out
# Anglicana legal fine-tune: KB27/CP40/JUST1/Coroners GT only, from r2.
# Runs concurrently with r6-core (independent base model + manifest).
# Expected ~2-4k training lines; 48h is a ceiling, early-stop will fire sooner.
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
BASE="$SRC/gm-htr-r2.mlmodel_best.mlmodel"
OUT="$SRC/gm-htr-anglicana"

cd "$SRC"
module load anaconda3 2>/dev/null || true

if [[ ! -s "$GT/metadata.jsonl" ]]; then
  echo "[anglicana] FATAL: metadata.jsonl missing — r6-core prep must finish first" >&2
  exit 1
fi
echo "[anglicana] using corpus $GT/metadata.jsonl"

# Build / normalize Anglicana PAGE GT from gt-mss (JUST1 + Done-lines + Coroners + holdout).
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_prep_env.sh"
GT_MSS="${GT_MSS:-$SRC/../gt-mss}"
export GT GT_MSS
"$PY_RUN" "$SRC/scripts/build_anglicana_gt.py" \
  --gt-mss-root "$GT_MSS" \
  --gt-dir "$GT" \
  --min-train 40

bash "$SRC/scripts/bridges_fix_kraken_numpy.sh"
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

python -c "import torch; print('CUDA:', torch.cuda.is_available())"

[[ -f "$BASE" ]] || { echo "Missing base model: $BASE"; exit 1; }
[[ -s "$GT/anglicana_train_manifest.txt" ]] || { echo "Anglicana manifest empty"; exit 1; }
[[ -s "$GT/anglicana_val_manifest.txt" ]] || { echo "Anglicana val manifest empty"; exit 1; }

echo "[anglicana] base=$BASE"
echo "[anglicana] train=$(wc -l < "$GT/anglicana_train_manifest.txt") val=$(wc -l < "$GT/anglicana_val_manifest.txt")"

# Smaller batch for modest legal GT; workers 2 avoids empty-set edge cases on tiny corpora.
ketos -d cuda:0 --workers 2 --precision bf16-mixed train \
  -i "$BASE" --resize union -f page \
  -q early --lag 20 --min-epochs 10 -N 150 -B 8 \
  -r 0.00005 --schedule cosine --augment \
  -t "$GT/anglicana_train_manifest.txt" -e "$GT/anglicana_val_manifest.txt" \
  -o "$OUT"

for candidate in \
  "$OUT.mlmodel_best.mlmodel" \
  "$OUT"_best.mlmodel \
  "$OUT-best.mlmodel"; do
  if [[ -f "$candidate" ]]; then
    cp -f "$candidate" "$SRC/gm-htr-anglicana_best.mlmodel"
    echo "[anglicana] exported $SRC/gm-htr-anglicana_best.mlmodel"
    break
  fi
done

bash "$SRC/scripts/bridges_post_training.sh" \
  --model-name gm-htr-anglicana \
  --model-path "$SRC/gm-htr-anglicana_best.mlmodel" \
  --val-manifest "$GT/anglicana_val_manifest.txt" \
  --round anglicana-v1 \
  --base gm-htr-r2_best \
  --notes "KB27/CP40/JUST1/Coroners Anglicana legal fine-tune, Bridges2 GPU-shared V100"
