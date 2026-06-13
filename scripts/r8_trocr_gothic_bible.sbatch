#!/bin/bash
#SBATCH -J trocr-r8-gothic
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=4
#SBATCH -t 24:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/%x-%j.out
# Fine-tune TrOCR on gothic_bible manifests (Paris Bible + CREMMA/HTRomance).
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
OUT="$SRC/models/trocr-gothic-bible"
VENV="${TROCR_VENV:-$SRC/../trocr-venv}"

cd "$SRC"
module load anaconda3 2>/dev/null || true

if [[ ! -s "$GT/gothic_bible_train_manifest.txt" ]]; then
  echo "[trocr-r8] building manifests"
  bash "$SRC/scripts/bridges_latin_corpus_prep.sh"
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "[trocr-r8] creating trocr venv at $VENV"
  python3 -m venv "$VENV"
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  pip install -U pip wheel
  pip install -e "$SRC/..[trocr]"
else
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
fi

python "$SRC/scripts/train_trocr_htr.py" \
  --train-manifest "$GT/gothic_bible_train_manifest.txt" \
  --val-manifest "$GT/gothic_bible_val_manifest.txt" \
  --output-dir "$OUT" \
  --pretrained microsoft/trocr-base-handwritten \
  --epochs 10 \
  --batch-size 8 \
  --lr 5e-5 \
  --device cuda

echo "[trocr-r8] done → $OUT"
