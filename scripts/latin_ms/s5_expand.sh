#!/usr/bin/env bash
# Stage 5 (optional) — Expand: protocol YAML → TEI XML → expand-diplomatic.
# 03_artifacts/ is untouched; 04_expanded/ holds derivatives.
#
# Usage:  s5_expand.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.latin-ms"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

JOB_DIR="${LATIN_MS_WORKSPACE}/jobs/${LATIN_MS_JOB_ID}"
ARTIFACTS_DIR="${JOB_DIR}/03_artifacts"
TEI_DIR="${JOB_DIR}/.tei_stage"
EXPANDED_DIR="${JOB_DIR}/04_expanded"
# expand-diplomatic upstream: https://github.com/buzzcauldron/expand-diplomatic
# MAGIC_ELISE_ROOT name retained for backward compat with older configs.
EXPAND_DIPLOMATIC_ROOT="${MAGIC_ELISE_ROOT:-${HOME}/Projects/expand-diplomatic}"
if [[ ! -d "$EXPAND_DIPLOMATIC_ROOT" ]]; then
    echo "ERROR: expand-diplomatic not found at $EXPAND_DIPLOMATIC_ROOT" >&2
    echo "  Install with: git clone https://github.com/buzzcauldron/expand-diplomatic.git ~/Projects/expand-diplomatic" >&2
    exit 1
fi
mkdir -p "$TEI_DIR" "$EXPANDED_DIR"

# YAML → TEI (transcriber-shell canonical logic)
echo "==> Stage 5: YAML → TEI XML"
transcriber-shell yaml-to-tei --dir "$ARTIFACTS_DIR" --out-dir "$TEI_DIR"

TEI_COUNT=$(find "$TEI_DIR" -name "*_tei.xml" | wc -l | tr -d ' ')
[[ "$TEI_COUNT" -eq 0 ]] && { echo "ERROR: no YAML in ${ARTIFACTS_DIR}. Run s4_transcribe.sh first." >&2; exit 1; }

# Propagate Google key from transcriber-shell config.
# expand-diplomatic calls load_dotenv() on its own .env which can hold a stale
# GEMINI_API_KEY. load_dotenv defaults to override=False, so an already-set
# env var wins — set BOTH names to the same valid key here.
_GKEY="$(python3 -c "from transcriber_shell.config import Settings; s=Settings(); print(s.google_api_key or '')" 2>/dev/null)"
if [[ -n "$_GKEY" ]]; then
    export GOOGLE_API_KEY="$_GKEY"
    export GEMINI_API_KEY="$_GKEY"
fi
# Bound per-call latency: expand-diplomatic has no default timeout and we hit a
# multi-hour hang on Google's TCP socket. 120s per call, with retries handled
# upstream, keeps stage 5 alive.
export GEMINI_TIMEOUT="${GEMINI_TIMEOUT:-120}"
export GEMINI_RETRY_ATTEMPTS="${GEMINI_RETRY_ATTEMPTS:-3}"

echo "==> Stage 5: expand-diplomatic (${EXPAND_DIPLOMATIC_BACKEND:-gemini}) → ${EXPANDED_DIR}"
EXPAND_ARGS=(
    --batch-dir "$TEI_DIR"
    --out-dir "$EXPANDED_DIR"
    --backend "${EXPAND_DIPLOMATIC_BACKEND:-gemini}"
    --model "${EXPAND_DIPLOMATIC_MODEL:-gemini-2.5-flash}"
    --modality "${EXPAND_DIPLOMATIC_MODALITY:-full}"
    --passes "${EXPAND_DIPLOMATIC_PASSES:-2}"
    # Run N docs in parallel; serial batch ran ~25 min/doc and we kept seeing
    # state-related hangs at doc 5. Even modest parallelism (3) wraps a 7-doc
    # job in roughly 3× one doc's time while spreading any hang risk.
    --parallel-files "${EXPAND_DIPLOMATIC_PARALLEL_FILES:-3}"
)
[[ -n "${EXPAND_DIPLOMATIC_LOCAL_MODEL:-}" ]] && EXPAND_ARGS+=(--local-model "$EXPAND_DIPLOMATIC_LOCAL_MODEL")
[[ -f "${JOB_DIR}/expand_examples.json" ]] && EXPAND_ARGS+=(--examples "${JOB_DIR}/expand_examples.json")

(cd "$EXPAND_DIPLOMATIC_ROOT" && python3 -m expand_diplomatic "${EXPAND_ARGS[@]}")

XML_COUNT=$(find "$EXPANDED_DIR" -name "*.xml" | wc -l | tr -d ' ')
echo "==> Stage 5 done: ${XML_COUNT} expanded XML file(s) in ${EXPANDED_DIR}"
