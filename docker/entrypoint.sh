#!/usr/bin/env bash
# If the repo is mounted at /workspace, reinstall editable so local changes apply.
set -euo pipefail

if [[ -d /workspace && -f /workspace/pyproject.toml ]]; then
  pip install -q -e "/workspace[api,gemini,xml-xsd]" 2>/dev/null \
    || pip install -q -e "/workspace[api]"
  cd /workspace
fi

if [[ "${1:-}" == "bash" || "${1:-}" == "/bin/bash" ]]; then
  shift || true
  exec /bin/bash "$@"
fi

exec "$@"
