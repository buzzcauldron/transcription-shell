#!/usr/bin/env bash
# Submit Bridges GPU HTR for control non-computus miscellany jobs already staged
# under JOBS_ROOT (images in 00_sources_chunks or 01_pages_2500).
#
# Usage (on Bridges login):
#   bash scripts/submit_bridges_control_htr.sh job_id [job_id ...]
#   bash scripts/submit_bridges_control_htr.sh --all
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SBATCH="${BRIDGES_CONTROL_HTR_SBATCH:-$ROOT/scripts/bridges_control_htr_job.sbatch}"
JOBS_ROOT="${JOBS_ROOT:-/ocean/projects/hum260002p/sstrickland/control_miscellany_htr_jobs}"
ACCOUNT="${SLURM_ACCOUNT:-hum260002p}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 job_id [job_id ...] | $0 --all" >&2
  exit 1
fi

mkdir -p "$JOBS_ROOT/logs"

ids=()
if [[ "$1" == "--all" ]]; then
  for d in "$JOBS_ROOT"/ctrl_*; do
    [[ -d "$d" ]] || continue
    ids+=("$(basename "$d")")
  done
else
  ids=("$@")
fi

for jid in "${ids[@]}"; do
  if [[ ! -d "$JOBS_ROOT/$jid/00_sources_chunks" && ! -d "$JOBS_ROOT/$jid/01_pages_2500" ]]; then
    echo "SKIP $jid — no images under $JOBS_ROOT/$jid" >&2
    continue
  fi
  if [[ -f "$JOBS_ROOT/$jid/status/htr_bridges.DONE" ]]; then
    echo "SKIP $jid — already DONE" >&2
    continue
  fi
  mkdir -p "$JOBS_ROOT/$jid/status"
  sid=$(sbatch --parsable -A "$ACCOUNT" --export=ALL,JOB_ID="$jid",JOBS_ROOT="$JOBS_ROOT" \
    --job-name="ctrl-${jid:0:12}" "$SBATCH")
  echo "$jid $sid"
  echo "$sid" > "$JOBS_ROOT/$jid/status/htr_bridges.SLURM"
done
