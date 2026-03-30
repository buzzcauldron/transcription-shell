#!/usr/bin/env bash
# Local install: venv, editable install, Playwright Chromium, protocol submodule.
# Similar role to visual-page-editor/scripts/install-desktop.sh (non-Docker path).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

echo "==> Submodules (transcription-protocol)"
if [ -d .git ]; then
  git submodule update --init --recursive vendor/transcription-protocol || true
fi

if [ ! -f vendor/transcription-protocol/benchmark/validate_schema.py ]; then
  echo "Warning: vendor/transcription-protocol missing. Run: git submodule update --init vendor/transcription-protocol" >&2
fi

echo "==> Python venv (.venv)"
if [ -d .venv ] && ! .venv/bin/python -c "import sys" 2>/dev/null; then
  echo "Removing stale .venv (interpreter path invalid); recreating."
  rm -rf .venv
fi
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> pip install (api + dev + optional extras)"
pip install -U pip
pip install -e ".[api,gemini,xml-xsd,dev]"

echo "==> Playwright Chromium (Glyph Machina automation)"
playwright install chromium

if [ ! -f .env ] && [ -f .env.example ]; then
  echo "Tip: copy .env.example to .env and add API keys."
fi

echo "==> Done. Activate with: source .venv/bin/activate"
echo "    GUI: transcriber-shell gui"
echo "    CLI: transcriber-shell --help   (package name; repo folder is transcription-shell)"
echo "    Or Docker: ./docker-run.sh / ./docker-run.sh shell"
