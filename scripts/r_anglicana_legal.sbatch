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

# Filter metadata.jsonl to Anglicana-only manifests (clean python, no kraken env).
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_prep_env.sh"
"$PY_RUN" - <<'PYEOF'
import json, os, pathlib, sys

gt = pathlib.Path(os.environ["GT"])
meta = gt / "metadata.jsonl"
if not meta.is_file():
    sys.exit("metadata.jsonl not found")

train, val = [], []
for line in meta.read_text().splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if row.get("script") != "anglicana":
        continue
    if row["split"] == "train":
        train.append(row["xml"])
    elif row["split"] == "val":
        val.append(row["xml"])

(gt / "anglicana_train_manifest.txt").write_text("\n".join(train) + "\n")
(gt / "anglicana_val_manifest.txt").write_text("\n".join(val) + "\n")
print(f"[anglicana] train={len(train)} val={len(val)}")
if len(train) < 100:
    sys.exit(f"Too few training lines ({len(train)}) — check GT rsync")
PYEOF

bash "$SRC/scripts/bridges_fix_kraken_numpy.sh"
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

python -c "import torch; print('CUDA:', torch.cuda.is_available())"

[[ -f "$BASE" ]] || { echo "Missing base model: $BASE"; exit 1; }
[[ -s "$GT/anglicana_train_manifest.txt" ]] || { echo "Anglicana manifest empty"; exit 1; }

echo "[anglicana] base=$BASE"
echo "[anglicana] train=$(wc -l < "$GT/anglicana_train_manifest.txt") val=$(wc -l < "$GT/anglicana_val_manifest.txt")"

ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  -i "$BASE" -f page \
  -q early --lag 20 --min-epochs 10 -N 150 -B 16 \
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
