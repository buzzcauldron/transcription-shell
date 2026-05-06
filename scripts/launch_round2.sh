#!/usr/bin/env bash
# Wait for round 1 to finish, then prepare GT manifests and launch round 2.
# Run directly on the CMU training server inside a screen/tmux session.
#
# Usage (on CMU server):
#   screen -S r2-train
#   bash ~/src/launch_round2.sh
#   Ctrl-A D  (detach)
#
# Env vars:
#   CORPUS        Corpus root dir (default: ~/src/htr-corpora)
#   ROUND2_GT     Output manifest dir (default: ~/src/round2-gt)
#   ROUND2_MODEL  Output model prefix (default: ~/src/gm-r2-htr)
#   R1_BEST       Round 1 best model (default: ~/src/gm-hf-htr_best.mlmodel)
#   MIN_XML       Minimum XML files before starting (default: 50000)
#   CMU_LRATE     Learning rate (default: 0.0001)
#   CMU_EPOCHS    Max epochs (default: 150)
#   CMU_LAG       Early stopping patience (default: 20)

set -euo pipefail

CORPUS="${CORPUS:-$HOME/src/htr-corpora}"
ROUND2_GT="${ROUND2_GT:-$HOME/src/round2-gt}"
ROUND2_MODEL="${ROUND2_MODEL:-$HOME/src/gm-r2-htr}"
R1_BEST="${R1_BEST:-$HOME/src/gm-hf-htr_best.mlmodel}"
MIN_XML="${MIN_XML:-50000}"
CMU_LRATE="${CMU_LRATE:-0.0001}"
CMU_EPOCHS="${CMU_EPOCHS:-150}"
CMU_LAG="${CMU_LAG:-20}"

LOG="$ROUND2_GT/r2-prepare.log"
mkdir -p "$ROUND2_GT"
exec > >(tee -a "$LOG") 2>&1

echo "=== Round 2 Launcher: $(date) ==="
echo "Corpus:      $CORPUS"
echo "Round2 GT:   $ROUND2_GT"
echo "R1 model:    $R1_BEST"
echo "Min XML:     $MIN_XML"
echo ""

# ── 1. Wait for round 1 ──────────────────────────────────────────────────────

echo "[$(date '+%H:%M:%S')] Waiting for round 1 training to finish..."
while pgrep -f "ketos.*train" > /dev/null 2>&1; do
    stage=$(grep -a 'stage' "$HOME/src/train.log" 2>/dev/null | tail -1 | tr -d '\r' | grep -oP 'stage \d+' || echo "unknown stage")
    echo "[$(date '+%H:%M:%S')] Round 1 running — $stage"
    sleep 120
done
echo "[$(date '+%H:%M:%S')] Round 1 complete (or no ketos process found)."

# Resolve base model
if [[ -f "$R1_BEST" ]]; then
    echo "Best model found: $R1_BEST"
else
    FINAL="${R1_BEST/_best/}"
    if [[ -f "$FINAL" ]]; then
        R1_BEST="$FINAL"
        echo "No _best.mlmodel; using final checkpoint: $R1_BEST"
    else
        echo "ERROR: No round 1 model found at $R1_BEST or $FINAL"
        exit 1
    fi
fi

# ── 2. Wait for enough corpus data ───────────────────────────────────────────

echo ""
echo "[$(date '+%H:%M:%S')] Waiting for corpus data (need ≥ $MIN_XML XML files in $CORPUS)..."
while true; do
    xml_count=$(find "$CORPUS" -name "*.xml" 2>/dev/null | wc -l)
    echo "[$(date '+%H:%M:%S')] XML files available: $xml_count"
    [[ $xml_count -ge $MIN_XML ]] && break
    sleep 300
done
echo "[$(date '+%H:%M:%S')] Corpus threshold met."

# ── 3. Convert any HF PNG+.gt.txt pairs that are ready ───────────────────────

echo ""
echo "[$(date '+%H:%M:%S')] Converting HF line pairs to PageXML..."
source "$HOME/src/.venv/bin/activate" 2>/dev/null || true

for hf_dir in catmus-medieval tridis; do
    dir="$CORPUS/$hf_dir"
    [[ -d "$dir" ]] || continue
    pairs=$(find "$dir" -name "*.gt.txt" 2>/dev/null | wc -l)
    xmls=$(find "$dir" -name "*.xml" 2>/dev/null | wc -l)
    if [[ $pairs -gt 0 && $xmls -lt $((pairs / 2)) ]]; then
        echo "  Converting $hf_dir ($pairs pairs → PageXML)..."
        python3 "$HOME/src/hf_pairs_to_pagexml.py" --workers 4 "$dir" \
            || echo "  [WARN] conversion had errors for $hf_dir"
    else
        echo "  $hf_dir: $xmls XMLs already present (skipping)"
    fi
done

# ── 4. Build train / val manifests ───────────────────────────────────────────

echo ""
echo "[$(date '+%H:%M:%S')] Building manifests..."

find "$CORPUS" -name "*.xml" | sort > "$ROUND2_GT/all_xml.txt"
total=$(wc -l < "$ROUND2_GT/all_xml.txt")
echo "Total XML files: $total"

python3 - "$ROUND2_GT/all_xml.txt" "$ROUND2_GT" <<'PYEOF'
import sys, random, pathlib
manifest = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
lines = [l for l in manifest.read_text().strip().splitlines() if l]
random.seed(42)
random.shuffle(lines)
split = int(len(lines) * 0.95)
train, val = lines[:split], lines[split:]
(out / "train_manifest.txt").write_text("\n".join(train) + "\n")
(out / "val_manifest.txt").write_text("\n".join(val) + "\n")
print(f"Train: {len(train):,}   Val: {len(val):,}")
PYEOF

echo "[$(date '+%H:%M:%S')] Manifests written."

# ── 5. Launch round 2 training ───────────────────────────────────────────────

echo ""
echo "[$(date '+%H:%M:%S')] Launching round 2..."
echo "Base model:  $R1_BEST"
echo "Output:      $ROUND2_MODEL"
echo "Train:       $(wc -l < "$ROUND2_GT/train_manifest.txt") files"
echo "Val:         $(wc -l < "$ROUND2_GT/val_manifest.txt") files"
echo ""

export PYTORCH_ALLOC_CONF=expandable_segments:True

ketos -d cuda:0 --precision bf16-mixed --workers 4 train \
    -i "$R1_BEST" \
    --resize union \
    -f page \
    -q early \
    --lag $CMU_LAG \
    --min-epochs 5 \
    -N $CMU_EPOCHS \
    -B 32 \
    -r $CMU_LRATE \
    --schedule reduceonplateau \
    --sched-patience 5 \
    --augment \
    -t "$ROUND2_GT/train_manifest.txt" \
    -e "$ROUND2_GT/val_manifest.txt" \
    -o "$ROUND2_MODEL" \
    > "$HOME/src/train_r2.log" 2>&1

echo ""
echo "[$(date '+%H:%M:%S')] Round 2 training complete."
best="${ROUND2_MODEL}_best.mlmodel"
if [[ -f "$best" ]]; then
    echo "Best checkpoint: $best"
else
    echo "Output: $ROUND2_MODEL.mlmodel"
fi
