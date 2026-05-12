#!/usr/bin/env bash
# best_model.sh — print "PROVIDER MODEL" for the best available LLM.
# Priority:  claude-sonnet-4-20250514 (Anthropic)
#         >  gemini-2.5-pro  (Gemini, if key present)
#         >  gemini-2.5-flash (Gemini fallback)
#         >  gpt-4o  (OpenAI)
#
# Usage (in other scripts):
#   read -r PROVIDER MODEL < <(bash best_model.sh)
#   transcriber-shell run ... --provider "$PROVIDER" --model "$MODEL"
#
# Override by setting TRANSCRIBER_SHELL_DEFAULT_PROVIDER and/or
# TRANSCRIBER_SHELL_MODEL in the environment before calling.
set -euo pipefail

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
