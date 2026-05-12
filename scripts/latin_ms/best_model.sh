#!/usr/bin/env bash
# best_model.sh — resolve provider, LLM model, HTR model, seg model for a doc type.
#
# Usage:
#   read -r PROVIDER LLM_MODEL < <(bash best_model.sh)
#   bash best_model.sh --doc-type medieval_latin_legal
#   bash best_model.sh --doc-type medieval_latin_legal --component llm
#
# Output (default): "PROVIDER LLM_MODEL"
# With --component htr:  path to HTR .mlmodel
# With --component seg:  path to seg .mlmodel
# With --component prompt: prompt yaml filename
#
# Priority (LLM):  claude-sonnet-4-20250514 > gemini-2.5-pro > gemini-2.5-flash > gpt-4o
# Override via TRANSCRIBER_SHELL_DEFAULT_PROVIDER + TRANSCRIBER_SHELL_MODEL env vars.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOC_TYPE="${LATIN_MS_DOC_TYPE:-medieval_latin_legal}"
COMPONENT="llm"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --doc-type)   DOC_TYPE="$2"; shift 2 ;;
        --component)  COMPONENT="$2"; shift 2 ;;
        *) echo "Unknown: $1" >&2; exit 1 ;;
    esac
done

DOC_SPEC="${SCRIPT_DIR}/document_types/${DOC_TYPE}.yaml"

# ── Non-LLM components: read from doc type spec ──────────────────────────────
if [[ "$COMPONENT" != "llm" ]]; then
    if [[ ! -f "$DOC_SPEC" ]]; then
        echo "ERROR: unknown doc type '${DOC_TYPE}' (no ${DOC_SPEC})" >&2; exit 1
    fi
    python3 - "$DOC_SPEC" "$COMPONENT" "$HOME" "${LATIN_MS_WORKSPACE:-$HOME/latin-ms-workspace}" <<'PYEOF'
import sys, re
from pathlib import Path

spec_path, component, home, workspace = sys.argv[1:5]
text = Path(spec_path).read_text()

def extract(key):
    m = re.search(rf'^\s+{key}:\s+(.+)$', text, re.MULTILINE)
    return m.group(1).strip().strip('"\'') if m else ""

def resolve(val):
    val = val.replace("${HOME}", home)
    val = val.replace("${LATIN_MS_WORKSPACE}", workspace)
    return val

if component == "htr":
    print(resolve(extract("path")))
elif component == "seg":
    # segmentation path is after the seg: block
    import re
    m = re.search(r'segmentation:.*?path:\s+(.+)', text, re.DOTALL)
    print(resolve(m.group(1).strip().strip('"\'')) if m else "")
elif component == "prompt":
    print(extract("prompt"))
else:
    print("", file=sys.stderr)
    sys.exit(1)
PYEOF
    exit 0
fi

# ── LLM component ─────────────────────────────────────────────────────────────
# Honour explicit override first
if [[ -n "${TRANSCRIBER_SHELL_DEFAULT_PROVIDER:-}" && -n "${TRANSCRIBER_SHELL_MODEL:-}" ]]; then
    echo "${TRANSCRIBER_SHELL_DEFAULT_PROVIDER} ${TRANSCRIBER_SHELL_MODEL}"
    exit 0
fi

if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "anthropic ${TRANSCRIBER_SHELL_MODEL:-claude-sonnet-4-20250514}"
elif [[ -n "${GOOGLE_API_KEY:-}" ]] || [[ -n "${GEMINI_API_KEY:-}" ]]; then
    echo "gemini ${TRANSCRIBER_SHELL_MODEL:-gemini-2.5-pro}"
elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
    echo "openai ${TRANSCRIBER_SHELL_MODEL:-gpt-4o}"
else
    echo "ERROR: no API key found (ANTHROPIC_API_KEY, GOOGLE_API_KEY, OPENAI_API_KEY)" >&2
    exit 1
fi
