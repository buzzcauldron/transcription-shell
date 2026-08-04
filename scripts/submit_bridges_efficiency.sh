#!/usr/bin/env bash
# Sync efficiency fixture + harness to Bridges and submit GPU-shared job.
# Login node is submit-only — work runs on GPU-shared V100.
set -euo pipefail

SHELL_REPO="${SHELL_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
DTN="${BRIDGES_DTN:-bridges2-dtn}"
LOGIN="${BRIDGES_LOGIN:-bridges2}"
SHELL_DEST="${BRIDGES_SHELL_SRC:-/ocean/projects/hum260002p/sstrickland/transcriber-shell/src}"
FIX_REMOTE="$SHELL_DEST/benchmark/efficiency_fixture"
NYPL_PAGES="${NYPL_PAGES:-$HOME/latin-ms-workspace/jobs/nypl_computus_text_3}"
SEG_LOCAL="${SEG_LOCAL:-$HOME/src/latin_documents/kraken-merged-seg.mlmodel_best.mlmodel}"

echo "[bridges-eff] prepare local fixture staging"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
# One NYPL page + lines XML (skip-gm → measure HTR on GPU)
IMG=$(ls "$NYPL_PAGES"/01_pages/*.jpg 2>/dev/null | head -1 || true)
if [[ -z "$IMG" ]]; then
  echo "error: no NYPL page under $NYPL_PAGES/01_pages" >&2
  exit 1
fi
STEM=$(basename "$IMG" .jpg)
XML="$NYPL_PAGES/02_lines/${STEM}.xml"
cp "$IMG" "$STAGE/"
[[ -f "$XML" ]] && cp "$XML" "$STAGE/"
cp "$SHELL_REPO/fixtures/prompt.example.yaml" "$STAGE/"
[[ -f "$SEG_LOCAL" ]] && cp "$SEG_LOCAL" "$STAGE/"

echo "[bridges-eff] sync scripts + runtime + fixture"
ssh -o BatchMode=yes "$LOGIN" "mkdir -p '$SHELL_DEST/scripts' '$SHELL_DEST/transcriber_shell/runtime' '$FIX_REMOTE' '$SHELL_DEST/benchmark/results/efficiency'"
rsync -az -e "ssh -o BatchMode=yes" \
  "$SHELL_REPO/scripts/efficiency_run.py" \
  "$SHELL_REPO/scripts/efficiency_htr.sbatch" \
  "${DTN}:${SHELL_DEST}/scripts/"
rsync -az -e "ssh -o BatchMode=yes" \
  "$SHELL_REPO/src/transcriber_shell/runtime/" \
  "${DTN}:${SHELL_DEST}/transcriber_shell/runtime/"
# Ensure package init path exists for imports from $SRC
rsync -az -e "ssh -o BatchMode=yes" \
  "$SHELL_REPO/src/transcriber_shell/" \
  "${DTN}:${SHELL_DEST}/transcriber_shell/" \
  --include='*/' --include='*.py' --exclude='*'
rsync -az -e "ssh -o BatchMode=yes" \
  "$STAGE/" "${DTN}:${FIX_REMOTE}/"

# Cancel prior pending eff-htr if still queued (optional)
if [[ "${CANCEL_OLD:-1}" == "1" ]]; then
  ssh -o BatchMode=yes "$LOGIN" "bash -lc '
    squeue -u \$USER -h -n eff-htr -o %i 2>/dev/null | while read j; do
      echo cancelling \$j; scancel \$j || true
    done
  '" || true
fi

JOB=$(ssh -o BatchMode=yes "$LOGIN" "bash -lc '
  cd \"$SHELL_DEST\"
  sbatch --parsable -A hum260002p --qos=gpuinteract scripts/efficiency_htr.sbatch
'")

echo "[bridges-eff] job id: $JOB"
echo "Monitor: ssh $LOGIN squeue -u \$USER -j $JOB"
echo "Log:     ssh $LOGIN tail -f $SHELL_DEST/eff-htr-${JOB}.out"
echo "Pull:    rsync -az $DTN:$SHELL_DEST/benchmark/results/efficiency/ ./benchmark/results/efficiency/"
