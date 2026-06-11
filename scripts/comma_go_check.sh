#!/usr/bin/env bash
# Preflight before CoMMA re-recognition — run once extra /ocean memory is live.
set -euo pipefail

COMMA_ROOT="${COMMA_ROOT:-/ocean/projects/hum260002p/sstrickland/comma-rerecognition}"
SRC="${SRC:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
MIN_FREE_GB="${MIN_FREE_GB:-80}"

echo "=== CoMMA re-recognition preflight ==="
echo "comma root: $COMMA_ROOT"
echo "src root:   $SRC"
echo "min free:   ${MIN_FREE_GB} GB"
echo ""

fail=0
check() { echo "  OK  $1"; }
warn() { echo "  WARN $1"; }
bad() { echo "  FAIL $1"; fail=1; }

if [[ -d "$COMMA_ROOT" ]]; then
  free_gb=$(df -BG "$COMMA_ROOT" 2>/dev/null | tail -1 | tr -dc '0-9\n' | head -1 || echo 0)
  echo "ocean free: ${free_gb} GB"
  if [[ "${free_gb:-0}" -lt "$MIN_FREE_GB" ]]; then
    bad "Need >= ${MIN_FREE_GB} GB free at $COMMA_ROOT (have ${free_gb:-?} GB)"
  else
    check "Storage headroom"
  fi
else
  warn "COMMA_ROOT missing — create after quota increase"
fi

for m in \
  "$SRC/gm-htr-r7-full_best.mlmodel" \
  "$SRC/gm-htr-r6-core_best.mlmodel" \
  "$SRC/gm-htr-r5-best.mlmodel"; do
  if [[ -f "$m" ]]; then
    check "Model $(basename "$m")"
    break
  fi
done || bad "No gm-htr model found under $SRC"

[[ -d "$COMMA_ROOT/raw/comma-jsonl" ]] && check "comma-jsonl downloaded" \
  || warn "Run: COMMA_ROOT=$COMMA_ROOT bash $SRC/scripts/comma_acquire.sh"

if grep -rq "comma-rerecognition" "$SRC/latin-corpus-gt" 2>/dev/null; then
  bad "comma paths leaked into latin-corpus-gt — remove before any training"
else
  check "Training firewall (no comma in latin-corpus-gt)"
fi

echo ""
if [[ "$fail" -eq 0 ]]; then
  echo "Ready. Pilot:"
  echo "  sbatch $SRC/scripts/comma_recognition.sbatch"
else
  echo "Not ready — resolve FAIL items above."
  exit 1
fi
