#!/usr/bin/env bash
# Mirror selected HTR corpora from the CMU GPU host to a local GPU box.
#
# Designed to run *on the destination machine* (halxvi or similar) and pull
# from the CMU server (akdeniz) via rsync over SSH. Resumable: each corpus
# transfers independently; restarting the script skips already-synced files.
#
# Usage:
#   bash sync_corpora_to_local_gpu.sh                          # default subset (recommended)
#   bash sync_corpora_to_local_gpu.sh --all                    # every corpus
#   bash sync_corpora_to_local_gpu.sh corpus1 corpus2 ...      # explicit list
#
# Environment overrides:
#   CMU_HOST       SSH target (default: seth@akdeniz.lan.cmu.edu)
#   CMU_CORPORA    Remote corpora root (default: ~/src/htr-corpora)
#   LOCAL_CORPORA  Local destination (default: /home/sethj/disk3/htr-corpora)
#   MIN_FREE_GB    Abort if destination disk has less than this much free (default: 50)

set -euo pipefail

CMU_HOST="${CMU_HOST:-seth@akdeniz.lan.cmu.edu}"
CMU_CORPORA="${CMU_CORPORA:-~/src/htr-corpora}"
LOCAL_CORPORA="${LOCAL_CORPORA:-/home/sethj/disk3/htr-corpora}"
MIN_FREE_GB="${MIN_FREE_GB:-50}"

# ── Default subset: Latin-focused, drops the 110 GB Bullinger corpus ───────
DEFAULT_CORPORA=(
  catmus-medieval
  tridis
  home-charters
  himanis
  konigsfelden-charters
  ocrd-gt-structure-text
  cremma-medieval
  cremma-medieval-lat
  anr-endp
  htromance-documentary
  htromance-medieval-latin
  htromance-medieval-french
  boccace-htr
  paris-bible
  cremma-early-modern
  caroline-minuscule
  iforal
  ciham-liber
  htromance-spain
  onb-cod-940
  polish-latin-transcribathon
  htromance-italian
  carolingian-latin-vienna
  carolingian-latin-2025
  transcriboqurest-2024
  gwalther
  htromance-medieval-italian
  eutyches
)

ALL_CORPORA_REMOTE=(
  bullinger-htr
  "${DEFAULT_CORPORA[@]}"
)

CORPORA=()
case "${1:-}" in
  ""|--default)
    CORPORA=("${DEFAULT_CORPORA[@]}")
    ;;
  --all)
    CORPORA=("${ALL_CORPORA_REMOTE[@]}")
    ;;
  --help|-h)
    sed -n '2,12p' "$0"
    exit 0
    ;;
  *)
    CORPORA=("$@")
    ;;
esac

# ── Sanity checks ──────────────────────────────────────────────────────────
mkdir -p "$LOCAL_CORPORA"

# Refuse to start if the destination is critically low on space.
FREE_GB=$(df --output=avail -BG "$LOCAL_CORPORA" | tail -1 | tr -d 'G ')
if (( FREE_GB < MIN_FREE_GB )); then
  echo "Refusing to start: only ${FREE_GB} GB free at $LOCAL_CORPORA (need >= ${MIN_FREE_GB})." >&2
  exit 2
fi

echo "=== sync plan ==="
echo "  from : $CMU_HOST:$CMU_CORPORA"
echo "  to   : $LOCAL_CORPORA"
echo "  free : ${FREE_GB} GB"
echo "  corpora (${#CORPORA[@]}):"
for c in "${CORPORA[@]}"; do echo "    - $c"; done
echo

# ── Transfer loop ─────────────────────────────────────────────────────────
START=$(date -Iseconds)
LOG_FILE="$LOCAL_CORPORA/sync_$(date +%Y%m%d_%H%M%S).log"
echo "log: $LOG_FILE"
echo

for corpus in "${CORPORA[@]}"; do
  remote="$CMU_HOST:$CMU_CORPORA/$corpus/"
  local="$LOCAL_CORPORA/$corpus/"
  mkdir -p "$local"

  # Cheap pre-check: confirm the corpus exists remotely. If not, skip + log.
  if ! ssh -o BatchMode=yes "$CMU_HOST" "test -d $CMU_CORPORA/$corpus" 2>/dev/null; then
    echo "[skip] $corpus — not present on $CMU_HOST" | tee -a "$LOG_FILE"
    continue
  fi

  # Check if we still have headroom before each corpus.
  FREE_GB=$(df --output=avail -BG "$LOCAL_CORPORA" | tail -1 | tr -d 'G ')
  if (( FREE_GB < MIN_FREE_GB )); then
    echo "[abort] only ${FREE_GB} GB left; stopping before $corpus" | tee -a "$LOG_FILE"
    exit 3
  fi

  echo "[start] $(date -Iseconds) $corpus (free: ${FREE_GB} GB)" | tee -a "$LOG_FILE"
  if rsync -avzh --info=progress2 --partial \
        "$remote" "$local" 2>&1 | tee -a "$LOG_FILE"; then
    echo "[done ] $(date -Iseconds) $corpus" | tee -a "$LOG_FILE"
  else
    echo "[fail ] $(date -Iseconds) $corpus (rsync exit $?); continuing" | tee -a "$LOG_FILE"
  fi
done

echo
echo "=== sync complete ==="
echo "  started : $START"
echo "  ended   : $(date -Iseconds)"
echo "  total   : $(du -sh "$LOCAL_CORPORA" | awk '{print $1}')"
echo "  log     : $LOG_FILE"
