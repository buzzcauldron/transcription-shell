#!/usr/bin/env bash
# Stage 4 — Transcribe: lines XML → LLM → validated YAML.
# Reads from 01_pages/ + 02_lines/; writes to 03_artifacts/.
# Skips pages that already have a valid YAML (set TRANSCRIBER_SHELL_SKIP_SUCCESSFUL=true).
#
# Usage:  s4_transcribe.sh [--force]
#   --force: ignore existing YAMLs and retranscribe all pages.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}"
PAGES_DIR="${JOB_DIR}/01_pages"
LINES_DIR="${JOB_DIR}/02_lines"
ARTIFACTS_DIR="${JOB_DIR}/03_artifacts"
PROMPT="${SCRIPT_DIR}/prompt_latin.yaml"
mkdir -p "$ARTIFACTS_DIR"

export TRANSCRIBER_SHELL_ARTIFACTS_DIR="$ARTIFACTS_DIR"

SKIP_ARG="--skip-successful"
[[ "${1:-}" == "--force" ]] && SKIP_ARG=""

read -r PROVIDER _MODEL < <(bash "${SCRIPT_DIR}/best_model.sh")
MODEL_ARGS=(--model "$_MODEL")

echo "==> Stage 4: transcription (provider: ${PROVIDER}, model: ${_MODEL})"
echo "    pages:    ${PAGES_DIR}"
echo "    lines:    ${LINES_DIR}"
echo "    artifacts: ${ARTIFACTS_DIR}"

LINES_XML_COUNT=$(find "$LINES_DIR" -name "*.xml" 2>/dev/null | wc -l | tr -d ' ')

if [[ "$LINES_XML_COUNT" -gt 0 ]]; then
    # Pre-validated lines XML available — skip automated lineation.
    transcriber-shell batch "$PAGES_DIR" \
        --prompt "$PROMPT" \
        --provider "$PROVIDER" \
        "${MODEL_ARGS[@]}" \
        --skip-gm \
        --lines-xml-dir "$LINES_DIR" \
        --skip-lines-xml-validation \
        --htr-combination "${TRANSCRIBER_SHELL_HTR_COMBINATION:-off}" \
        --batch-report "${JOB_DIR}/transcription_report.json" \
        ${SKIP_ARG}
else
    # No lines XML: fall through to configured lineation backend.
    echo "  (no lines XML in 02_lines/ — running lineation + transcription together)"
    transcriber-shell batch "$PAGES_DIR" \
        --prompt "$PROMPT" \
        --provider "$PROVIDER" \
        "${MODEL_ARGS[@]}" \
        --lineation-backend "${TRANSCRIBER_SHELL_LINEATION_BACKEND:-mask}" \
        --continue-on-lineation-failure \
        --htr-combination "${TRANSCRIBER_SHELL_HTR_COMBINATION:-off}" \
        --batch-report "${JOB_DIR}/transcription_report.json" \
        ${SKIP_ARG}
fi

YAML_COUNT=$(find "$ARTIFACTS_DIR" -name "*_transcription.yaml" | wc -l | tr -d ' ')
echo "==> Stage 4 done: ${YAML_COUNT} YAML file(s) in ${ARTIFACTS_DIR}"
echo "    Validate any single file: transcriber-shell validate-yaml <path>"
