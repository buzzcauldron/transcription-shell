#!/usr/bin/env bash
# Stage 7 — Score: compute CER/WER for expanded pipeline output vs GT XMLs.
#
# Input:   04_expanded/out/*_tei_expanded.xml   (or --expanded-dir PATH)
# GT:      $LATIN_MS_GT_DIR  (env: TRANSCRIBER_SHELL_GT_DIR or LATIN_MS_GT_DIR)
# Output:  06_scores/score_report.{json,txt}
#
# Usage:   s7_score.sh [--gt-dir PATH] [--job-id ID]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

GT_DIR="${LATIN_MS_GT_DIR:-${HOME}/latin-ms-workspace/training/combined_gt}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --job-id)    LATIN_MS_JOB_ID="$2"; shift 2 ;;
        --gt-dir)    GT_DIR="$2"; shift 2 ;;
        *) echo "Unknown: $1" >&2; exit 1 ;;
    esac
done

JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}"
EXPANDED_DIR="${JOB_DIR}/04_expanded/out"
SCORES_DIR="${JOB_DIR}/06_scores"

echo "==> Stage 7: scoring ${EXPANDED_DIR}"
echo "    GT: ${GT_DIR}"

transcriber-shell score "$EXPANDED_DIR" \
    --gt "$GT_DIR" \
    --report "$SCORES_DIR"

echo ""
echo "========================================================"
echo "  Stage 7 done. Scores in: ${SCORES_DIR}"
echo "========================================================"
