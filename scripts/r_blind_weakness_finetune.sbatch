#!/bin/bash
#SBATCH -J htr-blind
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o %x-%j.out
# Targeted fine-tune driven by blind_test_training_plan.py / blind_test_targets.yaml.
#
# Submit:
#   BLIND_CASE=BM-MED-001 sbatch scripts/r_blind_weakness_finetune.sbatch
#   BLIND_CASE=BM-KB27 sbatch scripts/r_blind_weakness_finetune.sbatch
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
CASE="${BLIND_CASE:?Set BLIND_CASE e.g. BM-KB27 or BM-MED-001}"
PREFIX="${CASE,,}"
PREFIX="${PREFIX//-/_}"

# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export SRC CASE GT PREFIX

python3 - <<'PYEOF'
import json, os, pathlib, subprocess, sys, yaml

src = pathlib.Path(os.environ["SRC"])
gt = pathlib.Path(os.environ["GT"])
case = os.environ["CASE"]
prefix = os.environ["PREFIX"]

targets = yaml.safe_load((src / "scripts" / "blind_test_targets.yaml").read_text())
cfg = (targets.get("cases") or {}).get(case)
if not cfg:
    sys.exit(f"Unknown BLIND_CASE={case}")

out_name = cfg.get("output_model") or f"gm-htr-blind-{case.lower()}"
base = src / cfg["base_model"]
if not base.is_file():
    sys.exit(f"Missing base model: {base}")

plan_path = src / "artifacts" / "blind-test-training" / "plan.json"
if plan_path.is_file():
    plan = json.loads(plan_path.read_text())
    hit = next((p for p in plan.get("priorities", []) if p.get("case") == case), None)
    if hit:
        print(f"[blind] plan priority={hit.get('priority')} reason={hit.get('reason')}")

subprocess.check_call([
    sys.executable,
    str(src / "scripts" / "build_weakness_manifest.py"),
    "--case", case,
    "--gt-root", str(gt),
])

train_m = gt / f"{prefix}_train_manifest.txt"
val_m = gt / f"{prefix}_val_manifest.txt"
if not train_m.is_file() or train_m.stat().st_size == 0:
    sys.exit(f"Empty train manifest: {train_m}")

out = src / out_name
env_file = gt / f".blind_{prefix}.env"
env_file.write_text(
    f"BASE={base}\nOUT={out}\nTRAIN={train_m}\nVAL={val_m}\nMODEL_NAME={out_name}\n"
)
print(f"[blind] case={case} base={base} out={out}")
print(f"[blind] train={sum(1 for _ in open(train_m))} val={sum(1 for _ in open(val_m))}")
PYEOF

# shellcheck disable=SC1090
source "$GT/.blind_${PREFIX}.env"

export SKIP_BULLINGER_EXTRACT=1
bash "$SRC/scripts/bridges_latin_corpus_prep.sh" || true

echo "[blind] training $MODEL_NAME"
ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  -i "$BASE" -f page \
  -q early --lag 20 --min-epochs 10 -N 150 -B 16 \
  -r 0.00005 --schedule cosine --augment \
  -t "$TRAIN" -e "$VAL" \
  -o "$OUT"

for candidate in \
  "$OUT.mlmodel_best.mlmodel" \
  "$OUT"_best.mlmodel \
  "$OUT-best.mlmodel"; do
  if [[ -f "$candidate" ]]; then
    cp -f "$candidate" "$SRC/${MODEL_NAME}_best.mlmodel"
    echo "[blind] exported $SRC/${MODEL_NAME}_best.mlmodel"
    break
  fi
done

bash "$SRC/scripts/bridges_post_training.sh" \
  --model-name "$MODEL_NAME" \
  --model-path "$SRC/${MODEL_NAME}_best.mlmodel" \
  --val-manifest "$VAL" \
  --round "blind-${BLIND_CASE}" \
  --base "$(basename "$BASE")" \
  --notes "Blind-test targeted fine-tune for ${BLIND_CASE}"
