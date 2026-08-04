#!/usr/bin/env bash
# Batch-launch strigil acquisition for all computus manuscripts with archive pages.
#
# Reads references/computus-library/manifest.json and launches remote_stream_launch.sh
# for each entry where archive_ms_page is set and strigil_acquire is true.
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
failed=0

# Read manifest with Python since jq may not be available
while IFS=$'\t' read -r id source_url strigil_acquire strigil_flags; do
  [[ "$strigil_acquire" == "True" ]] || continue
  [[ -n "$source_url" && "$source_url" != "null" && "$source_url" != "None" ]] || { no_iiif=$((no_iiif + 1)); continue; }
  [[ -z "$FILTER" || "$id" == *"$FILTER"* ]] || continue

  # Derive job ID: lowercase, trim to 40 chars
  job_id=$(echo "$id" | tr '[:upper:]' '[:lower:]' | cut -c1-40)

  # Skip if job already exists
  if echo "$existing" | grep -qxF "$job_id"; then
    echo "SKIP (exists): $job_id"
    skipped=$((skipped + 1))
    continue
  fi

  extra="${strigil_flags:-}"
  [[ "$extra" == "null" || "$extra" == "None" ]] && extra=""

  echo "LAUNCH: $job_id"
  echo "  url: $source_url"
  [[ -n "$extra" ]] && echo "  flags: $extra"

  if [[ "$DRY_RUN" == "false" ]]; then
    if STREAM_REMOTE="$REMOTE" \
      STREAM_JOB_ID="$job_id" \
      STREAM_SOURCE_URL="$source_url" \
      STREAM_DOC_TYPE="computus_medieval_latin" \
      STREAM_TARGET_SLUG="${job_id}_partial" \
      STREAM_STRIGIL_FLAGS="$extra" \
      bash "$SCRIPT_DIR/remote_stream_launch.sh"
    then
      launched=$((launched + 1))
    else
      echo "FAIL: $job_id (launch exit $?)" >&2
      failed=$((failed + 1))
    fi
    # Brief pause between submissions to avoid overwhelming akdeniz
    sleep 5
  else
    launched=$((launched + 1))
  fi

done < <(python3 - <<'PY'
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path("scripts/computus").resolve()))
from _acquire_plan import strigil_flags

m = json.load(open("references/computus-library/manifest.json"))
for ms in m["manuscripts"]:
    # Prefer explicit iiif_manifest; fall back to CitCA archive_ms_page.
    url = ms.get("iiif_manifest") or ms.get("archive_ms_page") or ""
    acquire = bool(ms.get("strigil_acquire", False))
    flags = ms.get("strigil_flags") or (strigil_flags(url) if url else "")
    print(f"{ms['id']}\t{url}\t{acquire}\t{flags}")
PY
)

echo ""
echo "Done: launched=$launched skipped_exists=$skipped skipped_no_url=$no_iiif failed=$failed"
if [[ "$DRY_RUN" == "true" ]]; then
  echo "dry run — nothing actually submitted"
fi
exit "$failed"
