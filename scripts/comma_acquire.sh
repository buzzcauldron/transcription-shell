#!/usr/bin/env bash
# Download CoMMA data for inference-only re-recognition.
# NEVER copy into htr-corpora/ or latin-corpus-gt/.
#
# Usage:
#   # Lightweight metadata + text only (fast, ~500 MB):
#   bash scripts/comma_acquire.sh
#
#   # Per-line deep JSONL (line text + metadata, ~few GB):
#   bash scripts/comma_acquire.sh --with-deep-jsonl
#
#   # ALTO XML for consensus-mode comma_filter (bulk ALTO not on public HF yet):
#   bash scripts/comma_acquire.sh --with-alto
#
#   # Override locations:
#   COMMA_ROOT=/ocean/.../comma-rerecognition bash scripts/comma_acquire.sh --with-alto
#
# After this runs:
#   bash scripts/comma_go_check.sh          # preflight check
#   sbatch scripts/comma_recognition.sbatch  # run on compute node
#   python scripts/comma_filter.py --alto-dir $COMMA_ROOT/raw/comma-alto ...
#
# CoMMA reference: https://comma.inria.fr/homepage
# HuggingFace:     https://huggingface.co/comma-project

set -euo pipefail

COMMA_ROOT="${COMMA_ROOT:-/ocean/projects/hum260002p/sstrickland/comma-rerecognition}"
RAW="$COMMA_ROOT/raw"

# CoMMA HuggingFace repo IDs — verify at https://huggingface.co/comma-project
JSONL_REPO="${JSONL_REPO:-comma-project/comma-jsonl}"
DEEP_JSONL_REPO="${DEEP_JSONL_REPO:-comma-project/deep-jsonl}"
# Bulk ALTO is not published on HF (comma-other-formats is metadata-only).
# Override ALTO_REPO if Inria releases a public dataset; otherwise use IIIF pilot mode.
ALTO_REPO="${ALTO_REPO:-}"

WITH_ALTO=0
WITH_DEEP=0
for arg in "$@"; do
  [[ "$arg" == "--with-alto" ]] && WITH_ALTO=1
  [[ "$arg" == "--with-deep-jsonl" ]] && WITH_DEEP=1
done

mkdir -p "$RAW"
echo "[comma-acquire] destination: $RAW"
echo "[comma-acquire] TRAINING FIREWALL: never symlink this tree into htr-corpora/"
echo ""

# ── 1. comma-jsonl (metadata + full-document text, always) ──────────────────
echo "[comma-acquire] downloading comma-jsonl (${JSONL_REPO})..."
if command -v huggingface-cli >/dev/null 2>&1; then
  huggingface-cli download "$JSONL_REPO" \
    --repo-type dataset \
    --local-dir "$RAW/comma-jsonl" \
    --local-dir-use-symlinks False
else
  python3 - <<PY
from huggingface_hub import snapshot_download
from pathlib import Path
dest = Path("$RAW/comma-jsonl")
dest.mkdir(parents=True, exist_ok=True)
snapshot_download(
    repo_id="$JSONL_REPO",
    repo_type="dataset",
    local_dir=str(dest),
    local_dir_use_symlinks=False,
)
print(f"Downloaded to {dest}")
PY
fi
echo "[comma-acquire] comma-jsonl done."
echo ""

# ── 2. deep-jsonl (per-line CATMuS text + metadata, optional) ───────────────
if [[ "$WITH_DEEP" -eq 1 ]]; then
  echo "[comma-acquire] downloading deep-jsonl (${DEEP_JSONL_REPO})..."
  if command -v huggingface-cli >/dev/null 2>&1; then
    huggingface-cli download "$DEEP_JSONL_REPO" \
      --repo-type dataset \
      --local-dir "$RAW/deep-jsonl" \
      --local-dir-use-symlinks False
  else
    python3 - <<PY
from huggingface_hub import snapshot_download
from pathlib import Path
dest = Path("$RAW/deep-jsonl")
dest.mkdir(parents=True, exist_ok=True)
snapshot_download(
    repo_id="$DEEP_JSONL_REPO",
    repo_type="dataset",
    local_dir=str(dest),
    local_dir_use_symlinks=False,
)
print(f"Downloaded to {dest}")
PY
  fi
  echo "[comma-acquire] deep-jsonl done (use for line-level CER vs CATMuS in comma_filter)."
  echo ""
fi

# ── 3. ALTO XML (per-line geometry + CATMuS text, optional) ─────────────────
if [[ "$WITH_ALTO" -eq 1 ]]; then
  if [[ -z "$ALTO_REPO" ]]; then
    echo "ERROR: --with-alto requires ALTO_REPO (bulk ALTO not on https://huggingface.co/comma-project yet)."
    echo "  Use IIIF pilot mode (default) or pass ALTO_REPO=... when a dataset is published."
    exit 1
  fi
  echo "[comma-acquire] downloading ALTO XML files (${ALTO_REPO})..."
  echo "[comma-acquire] NOTE: this is large (~50 GB). Ensure /ocean quota is sufficient."
  echo "[comma-acquire]       Run comma_go_check.sh first to verify free space."
  echo ""

  # Download only XML files — skip page images (we fetch those via IIIF)
  if command -v huggingface-cli >/dev/null 2>&1; then
    huggingface-cli download "$ALTO_REPO" \
      --repo-type dataset \
      --local-dir "$RAW/comma-alto" \
      --local-dir-use-symlinks False \
      --include "**/*.xml" "**/*.alto" 2>/dev/null \
      || huggingface-cli download "$ALTO_REPO" \
           --repo-type dataset \
           --local-dir "$RAW/comma-alto" \
           --local-dir-use-symlinks False
  else
    python3 - <<PY
from huggingface_hub import snapshot_download
from pathlib import Path
dest = Path("$RAW/comma-alto")
dest.mkdir(parents=True, exist_ok=True)
# Try XML-only first; fall back to full download if filtering unsupported
try:
    snapshot_download(
        repo_id="$ALTO_REPO",
        repo_type="dataset",
        local_dir=str(dest),
        local_dir_use_symlinks=False,
        allow_patterns=["**/*.xml", "**/*.alto"],
    )
except TypeError:
    snapshot_download(
        repo_id="$ALTO_REPO",
        repo_type="dataset",
        local_dir=str(dest),
        local_dir_use_symlinks=False,
    )
print(f"Downloaded to {dest}")
PY
  fi

  # Validate the ALTO tree looks right
  ALTO_XML_COUNT=$(find "$RAW/comma-alto" -name "*.xml" -o -name "*.alto" 2>/dev/null | wc -l || echo 0)
  echo "[comma-acquire] ALTO XML files found: $ALTO_XML_COUNT"

  if [[ "$ALTO_XML_COUNT" -eq 0 ]]; then
    echo ""
    echo "WARNING: No ALTO XML files downloaded. The repo ID '${ALTO_REPO}' may be wrong."
    echo "  Check https://huggingface.co/comma-project for the correct dataset name."
    echo "  Override with: ALTO_REPO=comma-project/correct-name bash scripts/comma_acquire.sh --with-alto"
    echo "  comma_filter.py will fall back to confidence mode without ALTO."
  else
    echo "[comma-acquire] ALTO download complete. Use with:"
    echo "  python scripts/comma_filter.py --alto-dir $RAW/comma-alto ..."
  fi
else
  echo "[comma-acquire] Skipping ALTO (pass --with-alto to enable consensus-mode filtering)."
  echo "  Without ALTO, comma_filter.py uses model confidence scores as quality proxy."
fi

echo ""
echo "[comma-acquire] done."
echo "Next: bash scripts/comma_go_check.sh"
