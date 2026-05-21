#!/usr/bin/env bash
# Wait for the corpora-sync tmux session on halxvi (or any machine) to
# finish, then build a train/val manifest from the freshly-synced corpora
# and launch ketos training in a new tmux session.
#
# Designed to chain after sync_corpora_to_local_gpu.sh — picks up the data
# the moment it lands. Survives ssh disconnects via tmux.
#
# Usage (on halxvi):
#   bash launch_round_after_sync.sh                   # waits, then trains r5
#   ROUND=6 BASE_MODEL=~/src/gm-htr-r5_best.mlmodel bash launch_round_after_sync.sh
#
# Defaults baked in for the current goal: fine-tune from gm-htr-r2 with the
# review's conservative recipe (lr=1e-5, cosine schedule, augment, lag=20).

set -euo pipefail

# ── Knobs (env-overridable) ────────────────────────────────────────────────
ROUND="${ROUND:-5}"
CORPORA_DIR="${CORPORA_DIR:-/home/sethj/disk3/htr-corpora}"
GT_DIR="${GT_DIR:-/home/sethj/disk3/round${ROUND}-gt}"
BASE_MODEL="${BASE_MODEL:-$HOME/src/latin_documents/gm-htr-r2.mlmodel_best.mlmodel}"
OUT_MODEL="${OUT_MODEL:-/home/sethj/disk3/gm-htr-r${ROUND}}"
DEVICE="${DEVICE:-cuda:0}"
WORKERS="${WORKERS:-4}"
BATCH_SIZE="${BATCH_SIZE:-16}"
EPOCHS="${EPOCHS:-100}"
LRATE="${LRATE:-0.00001}"
LAG="${LAG:-20}"
PRECISION="${PRECISION:-bf16-mixed}"
SCHEDULE="${SCHEDULE:-cosine}"
SYNC_SESSION="${SYNC_SESSION:-corpora-sync}"
TRAIN_SESSION="${TRAIN_SESSION:-r${ROUND}-train}"

LOG_DIR="${LOG_DIR:-/home/sethj/disk3/training_logs}"
mkdir -p "$LOG_DIR" "$GT_DIR"
LOG_FILE="$LOG_DIR/r${ROUND}-train_$(date +%Y%m%d_%H%M%S).log"

# ── 1. Wait for the sync tmux session to disappear ─────────────────────────
echo "[$(date -Iseconds)] waiting for tmux session '$SYNC_SESSION' to finish…"
while tmux has-session -t "$SYNC_SESSION" 2>/dev/null; do
  sleep 60
done
echo "[$(date -Iseconds)] sync session ended."

# Sanity: make sure the corpus dir actually has content.
if [ ! -d "$CORPORA_DIR" ] || [ -z "$(ls -A "$CORPORA_DIR" 2>/dev/null)" ]; then
  echo "Refusing to train: $CORPORA_DIR empty or missing." >&2
  exit 1
fi

# ── 2. Build train / val manifest from the synced corpora ─────────────────
echo "[$(date -Iseconds)] building manifests from $CORPORA_DIR…"

ALL_XML="$GT_DIR/all_xml.txt"
find "$CORPORA_DIR" -name "*.xml" | sort > "$ALL_XML"
TOTAL=$(wc -l < "$ALL_XML")
echo "  total XML files: $TOTAL"

if (( TOTAL < 1000 )); then
  echo "Refusing to train: only ${TOTAL} XML files found. Did the sync finish?" >&2
  exit 1
fi

# 95/5 split with a fixed seed so resumed runs stay stable.
python3 - "$ALL_XML" "$GT_DIR" <<'PYEOF'
import pathlib, random, sys
manifest = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
lines = [l for l in manifest.read_text().splitlines() if l]
random.seed(42)
random.shuffle(lines)
cut = int(len(lines) * 0.95)
train, val = lines[:cut], lines[cut:]
(out / "train_manifest.txt").write_text("\n".join(train) + "\n")
(out / "val_manifest.txt").write_text("\n".join(val) + "\n")
print(f"  train: {len(train):,}   val: {len(val):,}")
PYEOF

# ── 3. Launch ketos in its own tmux session ───────────────────────────────
if tmux has-session -t "$TRAIN_SESSION" 2>/dev/null; then
  echo "tmux session '$TRAIN_SESSION' already exists; refusing to re-launch." >&2
  exit 2
fi

CMD="export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True; \
ketos -d $DEVICE --workers $WORKERS --precision $PRECISION train \
  -i $BASE_MODEL \
  --resize union -f page -q early \
  --lag $LAG --min-epochs 5 -N $EPOCHS -B $BATCH_SIZE \
  -r $LRATE --schedule $SCHEDULE --augment \
  -t $GT_DIR/train_manifest.txt \
  -e $GT_DIR/val_manifest.txt \
  -o $OUT_MODEL \
  2>&1 | tee $LOG_FILE"

echo "[$(date -Iseconds)] launching tmux session '$TRAIN_SESSION'…"
echo "  base : $BASE_MODEL"
echo "  out  : ${OUT_MODEL}_best.mlmodel (when ketos saves the best epoch)"
echo "  log  : $LOG_FILE"
tmux new-session -d -s "$TRAIN_SESSION" "$CMD"

sleep 3
if tmux has-session -t "$TRAIN_SESSION" 2>/dev/null; then
  echo "[$(date -Iseconds)] $TRAIN_SESSION is up."
  echo "  attach:  tmux attach -t $TRAIN_SESSION"
  echo "  detach:  Ctrl-b d"
  echo "  tail:    tail -f $LOG_FILE"
else
  echo "[$(date -Iseconds)] launch appears to have failed; check $LOG_FILE" >&2
  exit 3
fi
