#!/usr/bin/env bash
# Copy acquired control jobs from Constantine (Akdeniz) to Bridges ocean, then sbatch.
#
# Run from Akdeniz if it has PSC keys, or from a machine that can see both:
#   bash scripts/control_miscellany/sync_control_jobs_to_bridges.sh [job_id ...]
#   bash scripts/control_miscellany/sync_control_jobs_to_bridges.sh --all
set -euo pipefail

SRC="${CONTROL_JOBS_SRC:-/mnt/constantinople/seth/latin-ms-workspace/jobs_control_noncomputus}"
DEST_HOST="${BRIDGES_HOST:-bridges2-dtn}"
DEST="${CONTROL_JOBS_DEST:-/ocean/projects/hum260002p/sstrickland/control_miscellany_htr_jobs}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 job_id [job_id ...] | $0 --all" >&2
  exit 1
fi

ids=()
if [[ "$1" == "--all" ]]; then
  for d in "$SRC"/ctrl_*; do
    [[ -d "$d" ]] || continue
    ids+=("$(basename "$d")")
  done
else
  ids=("$@")
fi

ssh "$DEST_HOST" "mkdir -p '$DEST/logs'"
for jid in "${ids[@]}"; do
  job="$SRC/$jid"
  if [[ ! -d "$job/00_sources_chunks" && ! -d "$job/01_pages_2500" ]]; then
    echo "SKIP $jid — no images" >&2
    continue
  fi
  echo "[rsync] $jid → $DEST_HOST:$DEST/"
  rsync -a --partial --info=stats1 \
    --exclude 'transcription_batches/' \
    --exclude 'logs/*.nohup.log' \
    "$job" "$DEST_HOST:$DEST/"
done
echo "On Bridges login: bash scripts/submit_bridges_control_htr.sh ${ids[*]:---all}"
