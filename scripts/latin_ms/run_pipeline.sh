#!/usr/bin/env bash
# Latin manuscript pipeline — full end-to-end runner.
# Stages 1-4 run automatically; stages 5-6 are opt-in flags.
#
# Usage:
#   run_pipeline.sh [--from N] [--expand] [--normalize] [URL ...]
#
#   --from N     Resume from stage N (1-6).  Default: 1.
#   --expand     Run stage 5 (expand-diplomatic) after transcription.
#   --normalize  Run stage 6 (normalization) after transcription.
#   URLs         Passed directly to s1_acquire.sh (override LATIN_MS_SOURCES).
#
# Prerequisites:
#   1. Copy scripts/latin_ms/env.example → scripts/latin_ms/.env.latin-ms and fill in.
#   2. pip install -e /path/to/strigil (strigil command available)
#   3. pip install -e /path/to/transcription-shell (transcriber-shell command available)
#   4. pip install -e /path/to/magic-elise-tool  (expand_diplomatic, if using --expand)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"

# ── Key-leak guard ────────────────────────────────────────────────────────────
# Abort if the env file is tracked by git (would push secrets on next commit).
if [[ -f "$ENV_FILE" ]] && git -C "$SCRIPT_DIR" ls-files --error-unmatch "$ENV_FILE" &>/dev/null 2>&1; then
    echo "ERROR: ${ENV_FILE} is tracked by git — remove it from the index first:" >&2
    echo "  git rm --cached scripts/latin_ms/.env.latin-ms" >&2
    exit 1
fi

[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

FROM_STAGE=1
DO_EXPAND=0
DO_NORMALIZE=0
URLS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from)    FROM_STAGE="$2"; shift 2 ;;
        --expand)  DO_EXPAND=1; shift ;;
        --normalize) DO_NORMALIZE=1; shift ;;
        http*|https*) URLS+=("$1"); shift ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}"
echo "========================================================"
echo "  Latin MS pipeline  |  job: ${LATIN_MS_JOB_ID}"
echo "  workspace: ${JOB_DIR}"
echo "========================================================"

run_stage() {
    local N="$1"; shift
    if [[ "$N" -ge "$FROM_STAGE" ]]; then
        echo ""
        bash "${SCRIPT_DIR}/$1" "${@:2}"
    else
        echo "  (skipping stage ${N}: --from ${FROM_STAGE})"
    fi
}

run_stage 1 s1_acquire.sh "${URLS[@]+"${URLS[@]}"}"
run_stage 2 s2_crop.sh
run_stage 3 s3_lineate.sh
run_stage 4 s4_transcribe.sh

# Validate all produced YAMLs before proceeding to expansion
if [[ "$FROM_STAGE" -le 4 ]]; then
    echo ""
    echo "==> Validating transcription YAMLs..."
    FAIL_COUNT=0
    while IFS= read -r -d '' YAML; do
        if ! transcriber-shell validate-yaml "$YAML" &>/dev/null; then
            echo "  SCHEMA FAIL: $YAML" >&2
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi
    done < <(find "${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}/03_artifacts" -name "*_transcription.yaml" -print0)
    if [[ "$FAIL_COUNT" -gt 0 ]]; then
        echo "  $FAIL_COUNT YAML(s) failed schema validation — fix before expanding." >&2
        [[ "$DO_EXPAND" -eq 1 ]] && { echo "  Skipping stage 5." >&2; DO_EXPAND=0; }
    else
        echo "  All YAMLs valid."
    fi
fi

[[ "$DO_EXPAND" -eq 1 ]] && run_stage 5 s5_expand.sh
[[ "$DO_NORMALIZE" -eq 1 ]] && run_stage 6 s6_normalize.sh

echo ""
echo "========================================================"
echo "  Pipeline complete."
echo "  Artifacts: ${JOB_DIR}/03_artifacts/"
[[ "$DO_EXPAND" -eq 1 ]]    && echo "  Expanded:  ${JOB_DIR}/04_expanded/"
[[ "$DO_NORMALIZE" -eq 1 ]] && echo "  Normalized: ${JOB_DIR}/05_normalized/"
echo "========================================================"
