#!/usr/bin/env bash
# Stage 4 — Transcribe: lines XML → LLM → validated YAML.
# Reads from 01_pages/ + 02_lines/; writes to 03_artifacts/.
#
# Usage:  s4_transcribe.sh [--force]
#   --force: retranscribe all pages, ignore existing YAMLs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}"
PAGES_DIR="${JOB_DIR}/01_pages"
LINES_DIR="${JOB_DIR}/02_lines"
ARTIFACTS_DIR="${JOB_DIR}/03_artifacts"
DOC_TYPE="${LATIN_MS_DOC_TYPE:-medieval_latin_legal}"
mkdir -p "$ARTIFACTS_DIR"
export TRANSCRIBER_SHELL_ARTIFACTS_DIR="$ARTIFACTS_DIR"

SKIP_ARG="--skip-successful"
[[ "${1:-}" == "--force" ]] && SKIP_ARG=""

LINES_XML_COUNT=$(find "$LINES_DIR" -name "*.xml" 2>/dev/null | wc -l | tr -d ' ')
LINEATION_ARG=()
if [[ "$LINES_XML_COUNT" -gt 0 ]]; then
    LINEATION_ARG=(--skip-gm --lines-xml-dir "$LINES_DIR" --skip-lines-xml-validation)
else
    echo "  (no lines XML in 02_lines/ — running lineation + transcription together)"
    LINEATION_ARG=(--lineation-backend "${TRANSCRIBER_SHELL_LINEATION_BACKEND:-kraken}" --continue-on-lineation-failure)
fi

transcriber-shell batch "$PAGES_DIR" \
    --doc-type "$DOC_TYPE" \
    "${LINEATION_ARG[@]}" \
    --htr-combination "${TRANSCRIBER_SHELL_HTR_COMBINATION:-kraken_htr}" \
    --batch-report "${JOB_DIR}/transcription_report.json" \
    ${SKIP_ARG}

YAML_COUNT=$(find "$ARTIFACTS_DIR" -name "*_transcription.yaml" | wc -l | tr -d ' ')
echo "==> Stage 4 done: ${YAML_COUNT} YAML file(s) in ${ARTIFACTS_DIR}"
