#!/usr/bin/env bash
# Stage 3 — Lineation: produce one PageXML lines file per page in 02_lines/.
#
# Automated path (default): runs transcriber-shell batch --xml-only on 01_pages/
#   using the backend set in TRANSCRIBER_SHELL_LINEATION_BACKEND (mask/kraken).
#
# Manual / VPE path: skip this script, draw baselines in Visual Page Editor,
#   export PageXML to JOB_DIR/02_lines/{stem}.xml, then run s4_transcribe.sh.
#   Launch VPE with:  visual-page-editor  (opens GUI; open images from 01_pages/)
#
# Usage:  s3_lineate.sh [--manual-check]
#   --manual-check: validate existing 02_lines/ XMLs only, do not re-run lineation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}"
PAGES_DIR="${JOB_DIR}/01_pages"
LINES_DIR="${JOB_DIR}/02_lines"
PROMPT="${SCRIPT_DIR}/prompt_latin.yaml"
mkdir -p "$LINES_DIR"

MANUAL_CHECK=0
[[ "${1:-}" == "--manual-check" ]] && MANUAL_CHECK=1

# ── Validate existing XMLs only ───────────────────────────────────────────────
if [[ "$MANUAL_CHECK" -eq 1 ]]; then
    echo "==> Stage 3: validating existing PageXML in ${LINES_DIR}"
    FAIL=0
    for XML in "${LINES_DIR}"/*.xml; do
        [[ -e "$XML" ]] || { echo "  no .xml files found"; break; }
        if transcriber-shell validate-xml "$XML" &>/dev/null; then
            echo "  OK  ${XML##*/}"
        else
            echo "  FAIL ${XML##*/}"
            FAIL=1
        fi
    done
    [[ "$FAIL" -eq 0 ]] || { echo "ERROR: one or more XMLs failed validation." >&2; exit 1; }
    exit 0
fi

# ── Automated lineation ───────────────────────────────────────────────────────
# Use --xml-only so transcriber-shell writes lines XML but does not call the LLM.
# The artifacts dir for XML-only still needs to exist; we use a temp subdir.
LINEATION_ARTIFACTS="${JOB_DIR}/.lineation_artifacts"
export TRANSCRIBER_SHELL_ARTIFACTS_DIR="$LINEATION_ARTIFACTS"

echo "==> Stage 3: lineation (${TRANSCRIBER_SHELL_LINEATION_BACKEND:-mask}) → ${LINES_DIR}"
transcriber-shell batch "$PAGES_DIR" \
    --prompt "$PROMPT" \
    --lineation-backend "${TRANSCRIBER_SHELL_LINEATION_BACKEND:-mask}" \
    --xml-only \
    --batch-report "${JOB_DIR}/lineation_report.json"

# Copy the produced lines XML (PageXML) from artifacts into 02_lines/
# transcriber-shell writes <artifacts>/<job_id>/<stem>_lines.xml or similar;
# find and stage them flat into 02_lines/ named <stem>.xml.
find "$LINEATION_ARTIFACTS" -name "*_lines.xml" | while read -r F; do
    STEM=$(basename "$F" _lines.xml)
    cp "$F" "${LINES_DIR}/${STEM}.xml"
    echo "  staged ${STEM}.xml"
done

XML_COUNT=$(find "$LINES_DIR" -name "*.xml" | wc -l | tr -d ' ')
echo "==> Stage 3 done: ${XML_COUNT} lines XML file(s) in ${LINES_DIR}"
echo "    Open Visual Page Editor to inspect / repair any problematic pages:"
echo "    visual-page-editor"
