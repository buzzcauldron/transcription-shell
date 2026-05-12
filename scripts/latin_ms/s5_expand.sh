#!/usr/bin/env bash
# Stage 5 (optional) — Expand: run expand-diplomatic on validated YAML output.
# Converts protocol YAML → TEI XML, then calls expand-diplomatic.
# Output XML lands in 04_expanded/ as derivatives; 03_artifacts/ is untouched.
#
# Usage:  s5_expand.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

# Export the transcriber-shell Google key so expand-diplomatic can find it.
# expand-diplomatic reads GEMINI_API_KEY first, then GOOGLE_API_KEY.
# Unset GEMINI_API_KEY if it differs to avoid stale/expired key taking precedence.
_TS_GKEY="$(python3 -c "from transcriber_shell.config import Settings; s=Settings(); print(s.google_api_key or '')" 2>/dev/null)"
if [[ -n "$_TS_GKEY" ]]; then
    export GOOGLE_API_KEY="$_TS_GKEY"
    unset GEMINI_API_KEY  # prevent expired secondary key overriding
fi

JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}"
ARTIFACTS_DIR="${JOB_DIR}/03_artifacts"
TEI_DIR="${JOB_DIR}/.tei_stage"
EXPANDED_DIR="${JOB_DIR}/04_expanded"
MAGIC_ELISE="${MAGIC_ELISE_ROOT:-/Users/halxiii/Projects/magic-elise-tool}"
mkdir -p "$TEI_DIR" "$EXPANDED_DIR"

# ── Convert YAML → TEI XML ────────────────────────────────────────────────────
echo "==> Stage 5: converting YAML → TEI XML"
python3 "${SCRIPT_DIR}/yaml_to_tei.py" \
    --dir "$ARTIFACTS_DIR" \
    --out-dir "$TEI_DIR"

TEI_COUNT=$(find "$TEI_DIR" -name "*_tei.xml" | wc -l | tr -d ' ')
echo "    ${TEI_COUNT} TEI file(s) ready"

[[ "$TEI_COUNT" -eq 0 ]] && { echo "ERROR: no YAML found in ${ARTIFACTS_DIR}. Run s4_transcribe.sh first." >&2; exit 1; }

# ── expand-diplomatic ─────────────────────────────────────────────────────────
echo "==> Stage 5: expand-diplomatic (${EXPAND_DIPLOMATIC_BACKEND:-gemini}) → ${EXPANDED_DIR}"
EXPAND_ARGS=(
    --batch-dir "$TEI_DIR"
    --out-dir "$EXPANDED_DIR"
    --backend "${EXPAND_DIPLOMATIC_BACKEND:-gemini}"
    --modality "${EXPAND_DIPLOMATIC_MODALITY:-full}"
    --passes "${EXPAND_DIPLOMATIC_PASSES:-2}"
)
# Default to gemini-2.5-flash; override with EXPAND_DIPLOMATIC_MODEL in env
EXPAND_ARGS+=(--model "${EXPAND_DIPLOMATIC_MODEL:-gemini-2.5-flash}")
[[ -n "${EXPAND_DIPLOMATIC_LOCAL_MODEL:-}" ]] && EXPAND_ARGS+=(--local-model "$EXPAND_DIPLOMATIC_LOCAL_MODEL")
# Inject job-specific examples if present at JOB_DIR/expand_examples.json
EXAMPLES_FILE="${JOB_DIR}/expand_examples.json"
[[ -f "$EXAMPLES_FILE" ]] && EXPAND_ARGS+=(--examples "$EXAMPLES_FILE")

(cd "$MAGIC_ELISE" && python3 -m expand_diplomatic "${EXPAND_ARGS[@]}")

XML_COUNT=$(find "$EXPANDED_DIR" -name "*.xml" | wc -l | tr -d ' ')
echo "==> Stage 5 done: ${XML_COUNT} expanded XML file(s) in ${EXPANDED_DIR}"
echo "    Source of truth remains 03_artifacts/ YAML; 04_expanded/ is derivative."
