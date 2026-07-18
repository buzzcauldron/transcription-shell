#!/usr/bin/env bash
# Batch-launch strigil acquisition for all computus manuscripts with confirmed IIIF manifests.
#
# Reads references/computus-library/manifest.json and launches remote_stream_launch.sh
# for each entry where iiif_manifest is set and strigil_acquire is true.
# Skips entries whose job directory already exists on REMOTE.
#
# Usage:
#   bash scripts/batch_scrape_computus.sh [--dry-run] [--filter PATTERN]
#
# Options:
#   --dry-run        Print what would be launched, don't actually run
#   --filter PATTERN Only launch entries whose ID contains PATTERN
#   --remote HOST    Override default remote (default: akdeniz)
#   --jobs-root DIR  Override remote job root (default: ~/latin-ms-workspace/jobs)
#
# Examples:
#   bash scripts/batch_scrape_computus.sh --dry-run
#   bash scripts/batch_scrape_computus.sh --filter bl_
#   bash scripts/batch_scrape_computus.sh --filter einsiedeln

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$SCRIPT_DIR/../references/computus-library/manifest.json"
REMOTE="${STREAM_REMOTE:-akdeniz}"
JOBS_ROOT="${STREAM_JOBS_ROOT:-\$HOME/latin-ms-workspace/jobs}"
DRY_RUN=false
FILTER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)  DRY_RUN=true; shift ;;
    --filter)   FILTER="$2"; shift 2 ;;
    --remote)   REMOTE="$2"; shift 2 ;;
    --jobs-root) JOBS_ROOT="$2"; shift 2 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

# Get list of already-existing job dirs on remote
existing=$(ssh "$REMOTE" "ls $JOBS_ROOT/ 2>/dev/null || true")

launched=0
skipped=0
no_iiif=0

# Read manifest with Python since jq may not be available
while IFS=$'\t' read -r id iiif_manifest strigil_acquire strigil_flags; do
  [[ "$strigil_acquire" == "True" ]] || continue
  [[ -n "$iiif_manifest" && "$iiif_manifest" != "null" && "$iiif_manifest" != "None" ]] || { ((no_iiif++)); continue; }
  [[ -z "$FILTER" || "$id" == *"$FILTER"* ]] || continue

  # Derive job ID: lowercase, trim to 40 chars
  job_id=$(echo "$id" | tr '[:upper:]' '[:lower:]' | cut -c1-40)

  # Skip if job already exists
  if echo "$existing" | grep -qxF "$job_id"; then
    echo "SKIP (exists): $job_id"
    ((skipped++))
    continue
  fi

  extra="${strigil_flags:-}"
  [[ "$extra" == "null" || "$extra" == "None" ]] && extra=""

  echo "LAUNCH: $job_id"
  echo "  url: $iiif_manifest"
  [[ -n "$extra" ]] && echo "  flags: $extra"

  if [[ "$DRY_RUN" == "false" ]]; then
    STREAM_REMOTE="$REMOTE" \
    STREAM_JOB_ID="$job_id" \
    STREAM_SOURCE_URL="$iiif_manifest" \
    STREAM_DOC_TYPE="computus_medieval_latin" \
    STREAM_TARGET_SLUG="${job_id}_partial" \
    STREAM_STRIGIL_FLAGS="$extra" \
    bash "$SCRIPT_DIR/remote_stream_launch.sh"
    ((launched++))
    # Brief pause between submissions to avoid overwhelming akdeniz
    sleep 3
  else
    ((launched++))
  fi

done < <(python3 - <<'PY'
import json, sys
m = json.load(open('references/computus-library/manifest.json'))
for ms in m['manuscripts']:
    iiif = ms.get('iiif_manifest') or ''
    acquire = ms.get('strigil_acquire', False)
    flags = ms.get('strigil_flags') or ''
    print(f"{ms['id']}\t{iiif}\t{acquire}\t{flags}")
PY
)

echo ""
echo "Done: $launched launched, $skipped skipped (job exists), $no_iiif skipped (no IIIF manifest)"
[[ "$DRY_RUN" == "true" ]] && echo "(dry run — nothing actually submitted)"
