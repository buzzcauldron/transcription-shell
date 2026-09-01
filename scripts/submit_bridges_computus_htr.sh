#!/usr/bin/env bash
# Submit Bridges GPU HTR for one or more computus job IDs already staged under JOBS_ROOT.
#
# Usage:
#   bash scripts/submit_bridges_computus_htr.sh job_id [job_id ...]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SBATCH="${BRIDGES_COMPUTUS_HTR_SBATCH:-$ROOT/scripts/bridges_computus_htr_job.sbatch}"
JOBS_ROOT="${JOBS_ROOT:-/ocean/projects/hum260002p/sstrickland/computus_htr_jobs}"
ACCOUNT="${SLURM_ACCOUNT:-hum260002p}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 job_id [job_id ...]" >&2
  exit 1
fi

mkdir -p "$JOBS_ROOT/logs"
for jid in "$@"; do
  if [[ ! -d "$JOBS_ROOT/$jid/00_sources_chunks" && ! -d "$JOBS_ROOT/$jid/01_pages_2500" ]]; then
    echo "SKIP $jid — no images under $JOBS_ROOT/$jid" >&2
    continue
  fi
  sid=$(sbatch --parsable -A "$ACCOUNT" --export=ALL,JOB_ID="$jid",JOBS_ROOT="$JOBS_ROOT" \
    --job-name="cwh-${jid:0:12}" "$SBATCH")
  echo "$jid $sid"
  echo "$sid" > "$JOBS_ROOT/$jid/status/htr_bridges.SLURM"
done
