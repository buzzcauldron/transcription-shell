#!/bin/bash
#SBATCH -J htr-r8-gothic-r
#SBATCH -p GPU-shared
#SBATCH --gres=gpu:v100-32:1
#SBATCH -N 1
#SBATCH --ntasks-per-node=5
#SBATCH -t 48:00:00
#SBATCH -A hum260002p
#SBATCH -o /ocean/projects/hum260002p/sstrickland/transcriber-shell/src/%x-%j.out
# Resume r8 Gothic Bible fine-tune (48h GPU-shared chunks; auto-chain on timeout).
set -euo pipefail

SRC=/ocean/projects/hum260002p/sstrickland/transcriber-shell/src
GT="$SRC/latin-corpus-gt"
OUT="$SRC/gm-htr-r8-gothic-bible"
EXPORT="$SRC/gm-htr-r8-gothic-bible_best.mlmodel"
CHAINED=0
TROCR_SUBMITTED=0

export_r8_best_from_ckpt() {
  bash "$SRC/scripts/bridges_export_kraken_checkpoint.sh" "$OUT" "$EXPORT" 2>/dev/null || true
}

submit_trocr_if_ready() {
  [[ -s "$EXPORT" ]] || return 0
  if squeue -u "$USER" -h -o "%j %T" | awk '$1=="trocr-r8-gothic" && ($2=="RUNNING" || $2=="PENDING") {found=1} END{exit !found}'; then
    echo "[r8-gothic-resume] trocr-r8-gothic already queued"
    return 0
  fi
  local trocr
  trocr=$(sbatch --parsable -A hum260002p "$SRC/scripts/r8_trocr_gothic_bible.sbatch")
  echo "[r8-gothic-resume] submitted trocr-r8-gothic job $trocr"
  TROCR_SUBMITTED=1
}

on_exit() {
  local ec=$?
  set +e
  local early=0
  for candidate in \
    "$OUT.mlmodel_best.mlmodel" \
    "$OUT"_best.mlmodel \
    "$OUT-best.mlmodel"; do
    if [[ -f "$candidate" ]]; then
      if [[ "$(readlink -f "$candidate")" != "$(readlink -f "$EXPORT")" ]]; then
        cp -f "$candidate" "$EXPORT"
      fi
      echo "[r8-gothic-resume] exported $EXPORT (early-stop)"
      early=1
      break
    fi
  done

  if [[ "$early" -eq 1 ]]; then
    submit_trocr_if_ready
    bash "$SRC/scripts/bridges_post_training.sh" \
      --model-name gm-htr-r8-gothic-bible \
      --model-path "$EXPORT" \
      --val-manifest "$GT/gothic_bible_val_manifest.txt" \
      --round r8-gothic-bible \
      --base gm-htr-r5-best \
      --notes "Gothic book Latin resume; early-stop export" || true
  else
    export_r8_best_from_ckpt
    if [[ "$CHAINED" -eq 0 ]] && [[ -n "${SLURM_JOB_ID:-}" ]]; then
      local next
      next=$(sbatch --parsable --dependency=afterany:"$SLURM_JOB_ID" -A hum260002p "$SRC/scripts/r8_gothic_bible_resume.sbatch")
      echo "[r8-gothic-resume] chaining next 48h chunk job $next (afterany:$SLURM_JOB_ID)"
      CHAINED=1
    fi
  fi
  exit "$ec"
}
trap on_exit EXIT

cd "$SRC"
module load anaconda3 2>/dev/null || true

[[ -s "$GT/gothic_bible_train_manifest.txt" ]] || {
  echo "[r8-gothic-resume] building manifests"
  bash "$SRC/scripts/bridges_latin_corpus_prep.sh"
}

bash "$SRC/scripts/bridges_fix_kraken_numpy.sh"
# shellcheck disable=SC1091
source "$SRC/scripts/bridges_kraken_activate.sh"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

CKPT=$(ls -t "$OUT"/checkpoint_*.ckpt 2>/dev/null | grep -v abort | head -1 || true)
[[ -n "$CKPT" ]] || { echo "No checkpoint in $OUT — run r8_gothic_bible_retrain.sbatch first"; exit 1; }

echo "[r8-gothic-resume] ckpt=$CKPT"
echo "[r8-gothic-resume] train=$(wc -l < "$GT/gothic_bible_train_manifest.txt") val=$(wc -l < "$GT/gothic_bible_val_manifest.txt")"

export_r8_best_from_ckpt || true

ketos -d cuda:0 --workers 5 --precision bf16-mixed train \
  --resume "$CKPT" --resize union -f page \
  -q early --lag 20 --min-epochs 5 -N 100 -B 16 \
  -r 0.00001 --schedule cosine --augment \
  -t "$GT/gothic_bible_train_manifest.txt" -e "$GT/gothic_bible_val_manifest.txt" \
  -o "$OUT"
