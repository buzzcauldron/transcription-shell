#!/usr/bin/env bash
# Local install: venv, editable install (core deps include tkinterdnd2), Playwright Chromium, protocol submodule.
# Chromium is required for the default lineation backend (glyph_machina). Similar role to visual-page-editor/scripts/install-desktop.sh.

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

echo "==> pip install (api + dev + optional extras; core package includes tkinterdnd2 for GUI drag-and-drop)"
pip install -U pip
pip install -e ".[api,gemini,xml-xsd,dev]"

echo "==> Playwright Chromium (default lineation: Glyph Machina)"
python -m playwright install chromium

echo "==> GUI sanity (tkinter + tkinterdnd2)"
if ! python -c "import tkinter; import tkinterdnd2" 2>/dev/null; then
  echo "Warning: tkinter or tkinterdnd2 import failed after pip install." >&2
  echo "  On Debian/Ubuntu, install system tkinter: sudo apt install python3-tk" >&2
fi

if [ ! -f .env ] && [ -f .env.example ]; then
  echo "Tip: copy .env.example to .env and add API keys."
fi

echo "==> Done. Activate with: source .venv/bin/activate"
echo "    Local setup guide: docs/local-setup.md"
echo "    GUI: transcriber-shell gui"
echo "    CLI: transcriber-shell --help   (package name; repo folder is transcription-shell)"
echo "    Or Docker: ./docker-run.sh / ./docker-run.sh shell"
